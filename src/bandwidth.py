# bandwidth.py

import argparse
import torch
import torchvision.transforms as transforms
from torch.utils.data import DataLoader
from torchvision.datasets import CIFAR10
from torchvision.models import resnet18
from tqdm import tqdm

from models import FedAvgCNN  # Import the FedAvgCNN model from the model file

# Bandwidth calculation function
def calculate_bandwidth(model, device):
    # Define a dummy input tensor
    dummy_input = torch.randn(1, 3, 32, 32).to(device)

    # Set the model to evaluation mode
    model.eval()

    # Move the model to the device
    model = model.to(device)

    # Perform a forward pass to calculate bandwidth
    with torch.no_grad():
        model(dummy_input)

    # Get the total number of bytes transferred
    total_bytes = sum(p.numel() * p.element_size() for p in model.parameters())

    # Convert bytes to gigabytes
    total_gb = total_bytes / (1024 ** 3)

    return total_gb


def main():
    # Set device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Initialize argument parser
    parser = argparse.ArgumentParser(description="Calculate model bandwidth")

    # Add model-specific arguments
    parser.add_argument(
        "--model",
        type=str,
        choices=["resnet18", "fedavgcnn"],  # Add the FedAvgCNN model choice
        default="resnet18",
        help="Model architecture",
    )

    # Parse command-line arguments
    args = parser.parse_args()

    # Define dataset and dataloader
    transform = transforms.Compose([transforms.ToTensor()])
    dataset = CIFAR10(root="./data", train=False, download=True, transform=transform)
    dataloader = DataLoader(dataset, batch_size=1, shuffle=False, num_workers=1)

    # Define the model based on the selected choice
    if args.model == "resnet18":
        model = resnet18(pretrained=False)
    elif args.model == "fedavgcnn":
        model = FedAvgCNN(dataset="cifar10", pruning_rate=0.2)  # Initialize the FedAvgCNN model

    # Calculate bandwidth
    bandwidth = calculate_bandwidth(model, device)
    print(f"Model bandwidth: {bandwidth:.2f} GB")


if __name__ == "__main__":
    main()
