#!/bin/bash
# Parallel speed test on the Hamilton CS HPC (starts its own vLLM, like run_eval.slurm). Submit from the repo root:
#     sbatch hpc/run_speed_test.slurm
#     N=20 SETTINGS='1:no_judge 16:no_judge' sbatch hpc/run_speed_test.slurm
# Download models first on the login node (the GPU nodes may have no internet):
#     hf download Qwen/Qwen2.5-32B-Instruct-AWQ
# Default GPU: one RTX PRO 6000 Blackwell (96 GB) on cs-hpc-node-6; nodes 1-5 have 16 GB, too small for 32B.
#SBATCH --job-name=gisun-speed
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition:1
#SBATCH --mem=32G
#SBATCH --time=04:00:00   # the cs QOS refuses longer jobs
#SBATCH --output=logs/%x_%j.out
#SBATCH --dependency=singleton   # one job of this name at a time: they share the node and its GPU

MODEL=${MODEL:-Qwen/Qwen2.5-32B-Instruct-AWQ}
JUDGE_MODEL=${JUDGE_MODEL:-}
MAX_LEN=${MAX_LEN:-16384}
GOLD=${GOLD:-datasets/gold_example.json}
HPC_DIR=${HPC_DIR:-/hpc/${USER%%@*}}   # $USER is "name@students.hamilton.edu"; the folder is /hpc/name

source "$HPC_DIR/miniconda3/etc/profile.d/conda.sh" && conda activate ai-guardrail
export HF_HOME=$HPC_DIR/hf_cache HF_HUB_OFFLINE=1        # use the downloaded model, don't contact Hugging Face
export XDG_CACHE_HOME=$HPC_DIR/.cache VLLM_CACHE_ROOT=$HPC_DIR/.cache/vllm   # keep caches out of the small home folder
export VLLM_USE_FLASHINFER_SAMPLER=0   # the nodes have no nvcc, and FlashInfer's sampler compiles with it
cd "$SLURM_SUBMIT_DIR"
nvidia-smi

serve() {  # serve <model> <port> <share of GPU memory>
    python -m vllm.entrypoints.openai.api_server --model "$1" --port "$2" \
        --enable-auto-tool-choice --tool-call-parser hermes \
        --max-model-len "$MAX_LEN" --gpu-memory-utilization "$3" &
    local pid=$!
    until curl -s "localhost:$2/v1/models" > /dev/null; do
        kill -0 $pid 2>/dev/null || { echo "vLLM failed to start ($1)"; exit 1; }
        sleep 10
    done
    PIDS="$PIDS $pid"
}

PORT=$((8100 + SLURM_JOB_ID % 800 * 2))   # per-job port: a fixed 8001 let a second job talk to the first job's server
if [ -n "$JUDGE_MODEL" ]; then
    serve "$MODEL" $PORT 0.55      # two servers share the GPU: start one, then the other
    serve "$JUDGE_MODEL" $((PORT + 1)) 0.35
    export GISUN_JUDGE_MODEL="$JUDGE_MODEL" GISUN_JUDGE_BASE_URL=http://localhost:$((PORT + 1))/v1
else
    serve "$MODEL" $PORT 0.90
fi

export GISUN_BACKEND=openai_compat GISUN_BASE_URL=http://localhost:$PORT/v1 GISUN_MODEL="$MODEL" GISUN_PARALLEL=16
python -m evaluation.speed_test --n "${N:-10}" --settings ${SETTINGS:-1:no_judge 4:no_judge 8:no_judge 16:no_judge}
kill $PIDS
