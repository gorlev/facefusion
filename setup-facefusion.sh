#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Function to print messages
print_message() {
    echo "========================================"
    echo "$1"
    echo "========================================"
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if the script is run as root for apt installations
if [ "$EUID" -ne 0 ]; then
    echo "Please run this script with sudo or as root."
    exit 1
fi

# Update package list
print_message "Updating package list..."
apt update -y

# Install Git
print_message "Installing Git..."
apt install -y git-all

# Install cURL
print_message "Installing cURL..."
apt install -y curl

# Install Miniconda
print_message "Installing Miniconda..."
curl -LO https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p -u "$HOME/miniconda"
rm Miniconda3-latest-Linux-x86_64.sh
export PATH="$HOME/miniconda/bin:$PATH"

# Install FFmpeg
print_message "Installing FFmpeg..."
apt install -y ffmpeg

# Install Mesa VA Drivers (Codec)
print_message "Installing Mesa VA Drivers..."
apt-get install -y mesa-va-drivers

# Initialize conda for all shells
print_message "Initializing Conda for all shells..."
conda init --all

# Source the bashrc to make conda available in this script
source "$HOME/.bashrc"

# Create the facefusion environment with Python 3.12
print_message "Creating Conda environment 'facefusion' with Python 3.12..."
conda create --name facefusion python=3.12 -y

# Activate the facefusion environment
print_message "Activating the 'facefusion' environment..."
conda activate facefusion

# Function to install NVIDIA accelerator
install_nvidia_accelerator() {
    print_message "Installing CUDA Runtime and cuDNN via Conda..."
    conda install -y -c conda-forge cuda-runtime=12.4.1 cudnn=9.2.1.18

    print_message "Installing TensorRT via pip..."
    pip install tensorrt==10.6.0 --extra-index-url https://pypi.nvidia.com
}

# Function to install AMD ROCm
install_amd_rocm() {
    print_message "Installing ROCm via apt..."
    apt install -y rocm

    print_message "Installing Python 3.10 and ROCm SMI via Conda..."
    conda install -y python=3.10 -c conda-forge
    conda install -y -c conda-forge rocm-smi=6.1.2
}

# Function to install Intel OpenVINO
install_intel_openvino() {
    print_message "Installing OpenVINO via Conda..."
    conda install -y -c conda-forge openvino=2024.3.0
}

# Detect GPU Vendor
print_message "Detecting GPU vendor..."
GPU_VENDOR=$(lspci | grep -E "VGA compatible controller" | grep -i -o -E "NVIDIA|AMD|Intel" | uniq || echo "None")

if [[ "$GPU_VENDOR" == "NVIDIA" ]]; then
    print_message "NVIDIA GPU detected."
    install_nvidia_accelerator
elif [[ "$GPU_VENDOR" == "AMD" ]]; then
    print_message "AMD GPU detected."
    install_amd_rocm
elif [[ "$GPU_VENDOR" == "Intel" ]]; then
    print_message "Intel GPU detected."
    install_intel_openvino
else
    print_message "No supported GPU detected. Skipping accelerator installations."
fi

# Clone the FaceFusion repository
print_message "Cloning the FaceFusion repository..."
git clone https://github.com/gorlev/facefusion.git

# Navigate into the repository directory
print_message "Entering the FaceFusion directory..."
cd facefusion

# Install the application
print_message "Installing the FaceFusion application..."
# Assuming {default, ...} needs to be replaced with 'default'
python install.py --onnxruntime cuda

# Reload the Conda environment
print_message "Reloading the Conda environment..."
conda deactivate
conda activate facefusion

# Completion message
print_message "Setup completed successfully!"

# Optional: Run the FaceFusion program
echo "To run the program, execute the following command:"
echo "python facefusion.py run"