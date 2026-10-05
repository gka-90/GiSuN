#!/bin/bash
# Serve the model on a GPU node so a laptop can use it through an SSH tunnel
# (the backend and pipeline keep running on the laptop). Submit from the repo root:
#     sbatch hpc/serve_model.slurm
# then on the laptop (see PIPELINE.md, "Use the HPC model from a laptop"):
#     ssh -N -L 8011:<node>:8011 <name>@150.209.91.65
# The GPU is shared: the job ends after --time; `scancel <job>` when you're done.
#SBATCH --job-name=gisun-serve
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition:1
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%j.out

MODEL=${MODEL:-Qwen/Qwen2.5-32B-Instruct-AWQ}
PORT=${PORT:-8011}
MAX_LEN=${MAX_LEN:-16384}
HPC_DIR=${HPC_DIR:-/hpc/${USER%%@*}}

source "$HPC_DIR/miniconda3/etc/profile.d/conda.sh" && conda activate ai-guardrail
export HF_HOME=$HPC_DIR/hf_cache HF_HUB_OFFLINE=1
export XDG_CACHE_HOME=$HPC_DIR/.cache VLLM_CACHE_ROOT=$HPC_DIR/.cache/vllm
export VLLM_USE_FLASHINFER_SAMPLER=0
echo "Serving $MODEL on $(hostname):$PORT until the job ends"

exec python -m vllm.entrypoints.openai.api_server --model "$MODEL" --served-model-name "$MODEL" --port "$PORT" \
    --enable-auto-tool-choice --tool-call-parser hermes \
    --max-model-len "$MAX_LEN" --gpu-memory-utilization 0.90
