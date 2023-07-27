import torch

class BandwidthEstimator:
    def __init__(self, model_size, num_clients, num_communication_rounds):
        self.model_size = model_size
        self.num_clients = num_clients
        self.num_communication_rounds = num_communication_rounds

    def measure_bandwidth(self):
        

        # Simulate sending model updates to the server and aggregating them
        for _ in range(self.num_communication_rounds):
            # Simulate sending model updates from clients to the server
            sent_updates = torch.empty(self.num_clients, self.model_size)

            # Simulate server aggregating the updates and updating the global model
            global_model = torch.empty(self.model_size)
            for update in sent_updates:
                global_model += update

        

        # Calculate total data transmitted over the network in bytes
        bandwidth_bytes = self.num_clients * self.model_size * self.num_communication_rounds

        

        # Convert bandwidth to megabytes 
        bandwidth_megabytes = bandwidth_bytes / (1024 * 1024)

        return bandwidth_megabytes, self.num_clients, self.num_communication_rounds, self.model_size