import pickle
import sys
import json
import os
import random
from argparse import Namespace
from collections import OrderedDict
from copy import deepcopy
from typing import Dict, List

import torch
from visdom import Visdom
from path import Path
from rich.console import Console
from rich.progress import track
from tqdm import tqdm
import time

_PROJECT_DIR = Path(__file__).parent.parent.parent.abspath()

sys.path.append(_PROJECT_DIR)

from src.utils import LOG_DIR, fix_random_seed, trainable_params
from src.models import MODEL_DICT
from src.args import get_fedavg_argparser
from src.client.fedavg import FedAvgClient


class FedAvgServer:
    def __init__(
        self,
        algo: str = "FedAvg",
        args: Namespace = None,
        unique_model=False,
        default_trainer=True,
    ):
        self.args = get_fedavg_argparser().parse_args() if args is None else args
        self.algo = algo
        self.unique_model = unique_model
        fix_random_seed(self.args.seed)
        with open(_PROJECT_DIR / "data" / self.args.dataset / "args.json", "r") as f:
            self.args.dataset_args = json.load(f)

        # get client party info
        self.train_clients: List[int] = None
        self.test_clients: List[int] = None
        self.client_num_in_total: int = None
        try:
            partition_path = _PROJECT_DIR / "data" / self.args.dataset / "partition.pkl"
            with open(partition_path, "rb") as f:
                partition = pickle.load(f)
        except:
            raise FileNotFoundError(f"Please partition {args.dataset} first.")
        self.train_clients = partition["separation"]["train"]
        self.test_clients = partition["separation"]["test"]
        self.client_num_in_total = partition["separation"]["total"]

        # init model(s) parameters
        self.device = torch.device(
            "cuda" if self.args.server_cuda and torch.cuda.is_available() else "cpu"
        )
        self.model = MODEL_DICT[self.args.model](self.args.dataset).to(self.device)
        self.model.check_avaliability()
        self.trainable_params_name, init_trainable_params = trainable_params(
            self.model, requires_name=True
        )
        # client_trainable_params is for pFL, which outputs exclusive model per client
        # global_params_dict is for regular FL, which outputs a single global model
        if self.unique_model:
            self.client_trainable_params: List[List[torch.Tensor]] = [
                deepcopy(init_trainable_params) for _ in self.train_clients
            ]
        self.global_params_dict: OrderedDict[str, torch.nn.Parameter] = OrderedDict(
            zip(self.trainable_params_name, deepcopy(init_trainable_params))
        )

        # To make sure all algorithms run through the same client sampling stream.
        # Some algorithms' implicit operations at client side may disturb the stream if sampling happens at each FL round's beginning.
        self.client_sample_stream = [
            random.sample(
                self.train_clients, int(self.client_num_in_total * self.args.join_ratio)
            )
            for _ in range(self.args.global_epoch)
        ]
        self.selected_clients: List[int] = []
        self.current_epoch = 0

        # variables for logging
        if self.args.visible:
            self.viz = Visdom()
            self.viz_win_name = (
                f"{self.algo}"
                + f"_{self.args.dataset}"
                + f"_{self.args.global_epoch}"
                + f"_{self.args.local_epoch}"
            )
        self.clients_metrics = {i: {} for i in self.train_clients}
        self.clients_acc_stats = {i: {} for i in self.train_clients}
        self.logger = Console(record=self.args.log, log_path=False, log_time=False)
        self.test_results: Dict[int, Dict[str, str]] = {}
        self.train_progress_bar = (
            track(
                range(self.args.global_epoch),
                "[bold green]Training...",
                console=self.logger,
            )
            if not self.args.log
            else tqdm(range(self.args.global_epoch), "Training...")
        )

        self.logger.log("=" * 20, "ALGORITHM:", self.algo, "=" * 20)
        self.logger.log("Experiment Arguments:", dict(self.args._get_kwargs()))

        # init trainer
        self.trainer = None
        if default_trainer:
            self.trainer = FedAvgClient(deepcopy(self.model), self.args, self.logger)

    def train(self):
        for E in self.train_progress_bar:
            self.current_epoch = E

            if (E + 1) % self.args.verbose_gap == 0:
                self.logger.log("-" * 26, f"TRAINING EPOCH: {E + 1}", "-" * 26)

            if (E + 1) % self.args.test_gap == 0:
                self.test()

            self.selected_clients = self.client_sample_stream[E]

            delta_cache = []
            weight_cache = []
            for client_id in self.selected_clients:

                client_local_params = self.generate_client_params(client_id)

                delta, weight, self.clients_metrics[client_id][E] = self.trainer.train(
                    client_id=client_id,
                    new_parameters=client_local_params,
                    verbose=((E + 1) % self.args.verbose_gap) == 0,
                )

                delta_cache.append(delta)
                weight_cache.append(weight)
                

            self.aggregate(delta_cache, weight_cache)
            self.log_info()
            print(self.aggregate)

    def test(self):
        loss_before, loss_after = [], []
        correct_before, correct_after = [], []
        num_samples = []
        for client_id in self.test_clients:
            client_local_params = self.generate_client_params(client_id)
            stats = self.trainer.test(client_id, client_local_params)

            correct_before.append(stats["before"]["test"]["correct"])
            correct_after.append(stats["after"]["test"]["correct"])
            loss_before.append(stats["before"]["test"]["loss"])
            loss_after.append(stats["after"]["test"]["loss"])
            num_samples.append(stats["before"]["test"]["size"])

        loss_before = torch.tensor(loss_before)
        loss_after = torch.tensor(loss_after)
        correct_before = torch.tensor(correct_before)
        correct_after = torch.tensor(correct_after)
        num_samples = torch.tensor(num_samples)

        self.test_results[self.current_epoch + 1] = {
            "loss": "{:.4f} -> {:.4f}".format(
                loss_before.sum() / num_samples.sum(),
                loss_after.sum() / num_samples.sum(),
            ),
            "accuracy": "{:.2f}% -> {:.2f}%".format(
                correct_before.sum() / num_samples.sum() * 100,
                correct_after.sum() / num_samples.sum() * 100,
            ),
        }

    @torch.no_grad()
    def update_client_params(self, client_params_cache: List[List[torch.nn.Parameter]]):
        if self.unique_model:
            for i, client_id in enumerate(self.selected_clients):
                self.client_trainable_params[client_id] = [
                    param.detach().to(self.device) for param in client_params_cache[i]
                ]
        else:
            raise RuntimeError(
                "FL system don't preserve params for each client (unique_model = False)."
            )

    def generate_client_params(self, client_id: int) -> OrderedDict[str, torch.Tensor]:
        if self.unique_model:
            return OrderedDict(
                zip(self.trainable_params_name, self.client_trainable_params[client_id])
            )
        else:
            return self.global_params_dict

    @torch.no_grad()
    def aggregate(self, delta_cache: List[List[torch.Tensor]], weight_cache: List[int]):
        self.weights = torch.tensor(weight_cache, device=self.device) / sum(weight_cache)
        

            
        print("***********************1")
        print(weight_cache)

        print("***********************2")
        
        delta_list = [list(delta.values()) for delta in delta_cache]
        aggregated_delta = [
            torch.sum(self.weights * torch.stack(diff, dim=-1), dim=-1)
            for diff in zip(*delta_list)
        
        ]

        for param, diff in zip(self.global_params_dict.values(), aggregated_delta):
            param.data -= diff.to(self.device)

    def check_convergence(self):
        train_correct_before = [
            [
                self.clients_metrics[cid][epoch]["before"]["train"]["correct"]
                for cid in clients
            ]
            for (epoch, clients) in enumerate(self.client_sample_stream)
        ]
        train_correct_after = [
            [
                self.clients_metrics[cid][epoch]["after"]["train"]["correct"]
                for cid in clients
            ]
            for (epoch, clients) in enumerate(self.client_sample_stream)
        ]
        train_num_samples = [
            [
                self.clients_metrics[cid][epoch]["before"]["train"]["size"]
                for cid in clients
            ]
            for (epoch, clients) in enumerate(self.client_sample_stream)
        ]
        test_correct_before = [
            [
                self.clients_metrics[cid][epoch]["before"]["test"]["correct"]
                for cid in clients
            ]
            for (epoch, clients) in enumerate(self.client_sample_stream)
        ]
        test_correct_after = [
            [
                self.clients_metrics[cid][epoch]["after"]["test"]["correct"]
                for cid in clients
            ]
            for (epoch, clients) in enumerate(self.client_sample_stream)
        ]
        test_num_samples = [
            [
                self.clients_metrics[cid][epoch]["before"]["test"]["size"]
                for cid in clients
            ]
            for (epoch, clients) in enumerate(self.client_sample_stream)
        ]

        self.logger.log("Convergence on train data:")
        self.logger.log("Accuracy (before):")
        acc_range = [90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
        min_acc_idx = 10
        max_acc = 0
        for E, (corr, n) in enumerate(zip(train_correct_before, train_num_samples)):
            acc_before = sum(corr) / sum(n) * 100.0
            for i, acc in enumerate(acc_range):
                if acc_before >= acc and acc_before > max_acc:
                    self.logger.log(
                        "{} achieved {}%({:.2f}%) at epoch: {}, {}".format(
                            self.algo, acc, acc_before, E, self.weights 
                        )
                    )
                    max_acc = acc_before
                    min_acc_idx = i
                    break
            acc_range = acc_range[:min_acc_idx]

        self.logger.log("\nAccuracy (after):")
        acc_range = [90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
        min_acc_idx = 10
        max_acc = 0
        for E, (corr, n) in enumerate(zip(train_correct_after, train_num_samples)):
            acc_after = sum(corr) / sum(n) * 100.0
            for i, acc in enumerate(acc_range):
                if acc_after >= acc and acc_after > max_acc:
                    self.logger.log(
                        "{} achieved {}%({:.2f}%) at epoch: {} with weights: {}".format(
                            self.algo, acc, acc_after, self.weights
                        )
                    )
                    max_acc = acc_after
                    min_acc_idx = i
                    break
            acc_range = acc_range[:min_acc_idx]

        self.logger.log("\nConvergence on test data:")
        self.logger.log("Accuracy (before):")
        acc_range = [90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
        min_acc_idx = 10
        max_acc = 0
        for E, (corr, n) in enumerate(zip(test_correct_before, test_num_samples)):
            acc_before = sum(corr) / sum(n) * 100.0
            for i, acc in enumerate(acc_range):
                if acc_before >= acc and acc_before > max_acc:
                    self.logger.log(
                        "{} achieved {}%({:.2f}%) at epoch: {} with weights :{}".format(
                            self.algo, acc, acc_before, E, self.weights
                        )
                    )
                    max_acc = acc_before
                    min_acc_idx = i
                    break
            acc_range = acc_range[:min_acc_idx]

        self.logger.log("\nAccuracy (after):")
        acc_range = [90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0]
        min_acc_idx = 10
        max_acc = 0
        for E, (corr, n) in enumerate(zip(test_correct_after, test_num_samples)):
            acc_after = sum(corr) / sum(n) * 100.0
            for i, acc in enumerate(acc_range):
                if acc_after >= acc and acc_after > max_acc:
                    self.logger.log(
                        "{} achieved {}%({:.2f}%) at epoch: {} with weights: {}".format(
                            self.algo, acc, acc_after, E, self.weights
                        )
                    )
                    max_acc = acc_after
                    min_acc_idx = i
                    break
            acc_range = acc_range[:min_acc_idx]

    def log_info(self):
        train_correct_before, train_correct_after = 0, 0
        test_correct_before, test_correct_after = 0, 0
        train_acc_before, train_acc_after = 0, 0
        test_acc_before, test_acc_after = 0, 0
        train_num_samples, test_num_samples = 0, 0

        # In the `user` split, there is no test data held by train clients, so plotting is unnecessary.
        if self.args.eval_test and self.args.dataset_args["split"] != "user":
            test_correct_before = torch.tensor(
                [
                    self.clients_metrics[cid][self.current_epoch]["before"]["test"][
                        "correct"
                    ]
                    for cid in self.selected_clients
                ]
            )
            test_correct_after = torch.tensor(
                [
                    self.clients_metrics[cid][self.current_epoch]["after"]["test"][
                        "correct"
                    ]
                    for cid in self.selected_clients
                ]
            )
            test_num_samples = torch.tensor(
                [
                    self.clients_metrics[cid][self.current_epoch]["before"]["test"][
                        "size"
                    ]
                    for cid in self.selected_clients
                ]
            )

            test_acc_before = (
                test_correct_before.sum(dim=-1, keepdim=True)
                / test_num_samples.sum()
                * 100.0
            ).item()
            test_acc_after = (
                test_correct_after.sum(dim=-1, keepdim=True)
                / test_num_samples.sum()
                * 100.0
            ).item()
            if self.args.visible:
                self.viz.line(
                    [test_acc_before],
                    [self.current_epoch],
                    win=self.viz_win_name,
                    update="append",
                    name="test_acc(before)",
                    opts=dict(
                        title=self.viz_win_name,
                        xlabel="Communication Rounds",
                        ylabel="Accuracy",
                    ),
                )
                self.viz.line(
                    [test_acc_after],
                    [self.current_epoch],
                    win=self.viz_win_name,
                    update="append",
                    name="test_acc(after)",
                )

        if self.args.eval_train:
            train_correct_before = torch.tensor(
                [
                    self.clients_metrics[cid][self.current_epoch]["before"]["train"][
                        "correct"
                    ]
                    for cid in self.selected_clients
                ]
            )
            train_correct_after = torch.tensor(
                [
                    self.clients_metrics[cid][self.current_epoch]["after"]["train"][
                        "correct"
                    ]
                    for cid in self.selected_clients
                ]
            )
            train_num_samples = torch.tensor(
                [
                    self.clients_metrics[cid][self.current_epoch]["before"]["train"][
                        "size"
                    ]
                    for cid in self.selected_clients
                ]
            )

            train_acc_before = (
                train_correct_before.sum(dim=-1, keepdim=True)
                / train_num_samples.sum()
                * 100.0
            ).item()
            train_acc_after = (
                train_correct_after.sum(dim=-1, keepdim=True)
                / train_num_samples.sum()
                * 100.0
            ).item()
            if self.args.visible:
                self.viz.line(
                    [train_acc_before],
                    [self.current_epoch],
                    win=self.viz_win_name,
                    update="append",
                    name="train_acc(before)",
                    opts=dict(
                        title=self.viz_win_name,
                        xlabel="Communication Rounds",
                        ylabel="Accuracy",
                    ),
                )
                self.viz.line(
                    [train_acc_after],
                    [self.current_epoch],
                    win=self.viz_win_name,
                    update="append",
                    name="train_acc(after)",
                )

        if self.args.save_allstats:
            for client_id in self.selected_clients:
                self.clients_acc_stats[client_id][
                    self.current_epoch
                ] = "acc (train): {:.2f}% -> {:.2f}%, acc (test): {:.2f}% -> {:.2f}%".format(
                    train_acc_before, train_acc_after, test_acc_before, test_acc_after
                )

    def run(self):
        if self.trainer is None:
            raise RuntimeError(
                "Specify your unique trainer or set `default_trainer` as True."
            )

        if self.args.visible:
            self.viz.close(win=self.viz_win_name)

        self.train()

        self.logger.log(
            "=" * 20, self.algo, "TEST RESULTS:", "=" * 20, self.test_results
        )

        self.check_convergence()

        # save log files
        if self.args.log or self.args.save_allstats:
            if not os.path.isdir(LOG_DIR / self.args.dataset):
                os.makedirs(LOG_DIR / self.args.dataset, exist_ok=True)

            if self.args.log:
                self.logger.save_text(LOG_DIR / self.args.dataset / f"{self.algo}.html")

            if self.args.save_allstats:
                with open(
                    LOG_DIR / self.args.dataset / f"{self.algo}_allstats.json", "w"
                ) as f:
                    json.dump(self.clients_acc_stats, f)

        # save trained model(s)
        if self.args.save_model:
            os.makedirs(_PROJECT_DIR / "models", exist_ok=True)
            model_name = f"{self.algo}_{self.args.dataset}_{self.args.global_epoch}_{self.args.model}.pt"
            if self.unique_model:
                torch.save(
                    self.client_trainable_params, _PROJECT_DIR / "models" / model_name
                )
            else:
                torch.save(
                    self.model.state_dict(), _PROJECT_DIR / "models" / model_name
                )


if __name__ == "__main__":
    server = FedAvgServer()
    server.run()
