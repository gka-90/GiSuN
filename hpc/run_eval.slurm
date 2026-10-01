#!/bin/bash
# Ablation on the HPC with vLLM. Check partition / GPU names with your HPC admins.
#SBATCH --job-name=gisun-eval
#SBATCH --gres=gpu:1
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x_%j.out

MODEL=${MODEL:-Qwen/Qwen2.5-32B-Instruct-AWQ}   # pick per GPU memory
source ~/miniconda3/etc/profile.d/conda.sh && conda activate ai-guardrail

# vLLM serves an OpenAI-compatible API; --enable-auto-tool-choice lets Qwen emit tool calls
python -m vllm.entrypoints.openai.api_server --model "$MODEL" --port 8001 \
    --enable-auto-tool-choice --tool-call-parser hermes --max-model-len 16384 &
until curl -s localhost:8001/v1/models > /dev/null; do sleep 10; done

export GISUN_BACKEND=openai_compat GISUN_BASE_URL=http://localhost:8001/v1 GISUN_MODEL="$MODEL" GISUN_PARALLEL=8
python -m evaluation.run_ablation --gold datasets/gold_example.json
python -m baseline.zero_tool --dataset datasets/gold_example.json
kill %1
