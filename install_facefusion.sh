#!/usr/bin/env bash
#
# FaceFusion Installation Script (English)
# Tested on Ubuntu/Debian based systems.
# Run as root or with sudo.

set -e  # Exit on error

if [[ $EUID -ne 0 ]]; then
  echo "[Error] Please run this script with sudo or as root."
  exit 1
fi

echo "Step 1) Installing system packages..."
apt-get update -y
apt-get install -y git-all curl ffmpeg mesa-va-drivers

echo
echo "Step 2) Installing Miniconda to /opt/miniconda..."
cd /tmp || exit
curl -LO https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh

bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/miniconda

# Make conda available in this script
export PATH="/opt/miniconda/bin:$PATH"

echo
echo "Step 3) Initializing conda in all shells..."
conda init --all >/dev/null 2>&1 || true
# Load conda for the current shell
eval "$(/opt/miniconda/bin/conda shell.bash hook)"

echo
echo "Step 4) Creating the facefusion conda environment..."
conda create --yes --name facefusion python=3.12

echo
echo "Step 5) Activating facefusion environment..."
conda activate facefusion

echo
echo "Step 6) Detecting GPU vendor..."
GPU_VENDOR=""
if lspci | grep -i nvidia >/dev/null 2>&1; then
    GPU_VENDOR="nvidia"
elif lspci | grep -i amd >/dev/null 2>&1; then
    GPU_VENDOR="amd"
elif lspci | grep -Ei 'intel.*(graphics|integrated|uhd)' >/dev/null 2>&1; then
    GPU_VENDOR="intel"
else
    GPU_VENDOR="none"
fi
echo "Detected GPU: $GPU_VENDOR"

echo
echo "Step 7) Installing accelerator libraries..."
case "$GPU_VENDOR" in
  "nvidia")
    echo "NVIDIA detected. Installing CUDA and TensorRT..."
    conda install --yes conda-forge::cuda-runtime=12.4.1 conda-forge::cudnn=9.2.1.18
    pip install tensorrt==10.6.0 --extra-index-url https://pypi.nvidia.com
    ;;
  "amd")
    echo "AMD detected. Installing ROCm..."
    apt-get install -y rocm
    # Please ensure that ROCm drivers are properly installed on your system.
    conda install --yes python=3.10 conda-forge::rocm-smi=6.1.2
    ;;
  "intel")
    echo "Intel detected. Installing OpenVINO..."
    conda install --yes conda-forge::openvino=2024.3.0
    ;;
  *)
    echo "No NVIDIA/AMD/Intel GPU found or unrecognized. Proceeding with default onnxruntime."
    ;;
esac

echo
echo "Step 8) Cloning the repository from https://github.com/gorlev/facefusion..."
cd /opt || exit
if [[ -d "facefusion" ]]; then
  echo "facefusion directory already exists, not cloning again."
  cd facefusion || exit
else
  git clone https://github.com/gorlev/facefusion
  cd facefusion || exit
fi

echo
echo "Step 9) Installing the application..."
# If GPU is NVIDIA -> install with 'cuda', otherwise 'default'
if [[ "$GPU_VENDOR" == "nvidia" ]]; then
    python install.py --onnxruntime cuda
else
    python install.py --onnxruntime default
fi

echo
echo "Step 10) Deactivating and re-activating the environment to ensure a clean state..."
conda deactivate
conda activate facefusion

echo
echo "Step 11) Done. Running FaceFusion..."
python facefusion.py run
