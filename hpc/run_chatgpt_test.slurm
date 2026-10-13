#!/bin/bash
# GiSuN (full agent mode) on the 65 real ChatGPT answers, on the Hamilton CS HPC. From the repo root:
#     sbatch hpc/run_chatgpt_test.slurm
#     MODES="full task_only" sbatch hpc/run_chatgpt_test.slurm
#     DATA=datasets/collected/claude_2026-10-12.json sbatch hpc/run_chatgpt_test.slurm   # Claude-written answers
#     RULES=0 DATA=... sbatch hpc/run_chatgpt_test.slurm   # agent only, no rules_only baseline
#     MODEL=Qwen/Qwen2.5-14B-Instruct-AWQ sbatch --gres=gpu:1 hpc/run_eval.slurm   # 16 GB RTX 5070 Ti nodes
#     JUDGE_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ sbatch hpc/run_eval.slurm           # separate Judge model (#11)
# Download models first on the login node (the GPU nodes may have no internet):
#     hf download Qwen/Qwen2.5-32B-Instruct-AWQ
# Default GPU: one RTX PRO 6000 Blackwell (96 GB) on cs-hpc-node-6; nodes 1-5 have 16 GB, too small for 32B.
#SBATCH --job-name=gisun-chatgpt
#SBATCH --partition=cs
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition:1
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x_%j.out

MODEL=${MODEL:-Qwen/Qwen2.5-32B-Instruct-AWQ}
JUDGE_MODEL=${JUDGE_MODEL:-}
MAX_LEN=${MAX_LEN:-16384}
DATA=${DATA:-"datasets/candidates_wildchat.json datasets/candidates_hc3.json"}
HPC_DIR=${HPC_DIR:-/hpc/${USER%%@*}}   # $USER is "name@students.hamilton.edu"; the folder is /hpc/name

source "$HPC_DIR/miniconda3/etc/profile.d/conda.sh" && conda activate ai-guardrail
export HF_HOME=$HPC_DIR/hf_cache HF_HUB_OFFLINE=1        # use the downloaded model, don't contact Hugging Face
export XDG_CACHE_HOME=$HPC_DIR/.cache VLLM_CACHE_ROOT=$HPC_DIR/.cache/vllm   # keep caches out of the small home folder
export XDG_CONFIG_HOME=$HPC_DIR/.config TRITON_CACHE_DIR=$HPC_DIR/.cache/triton \
       TORCHINDUCTOR_CACHE_DIR=$HPC_DIR/.cache/torchinductor VLLM_NO_USAGE_STATS=1 \
       TMPDIR=$HPC_DIR/tmp   # compile caches and temp files default to the (full) home folder
export HOME=$HPC_DIR/jobhome   # anything that still writes to ~ (e.g. ~/.nv, ~/.config) lands on /hpc, not the full /home
mkdir -p "$TMPDIR" "$XDG_CONFIG_HOME" "$HOME"
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

if [ -n "$JUDGE_MODEL" ]; then
    serve "$MODEL" 8001 0.55      # two servers share the GPU: start one, then the other
    serve "$JUDGE_MODEL" 8002 0.35
    export GISUN_JUDGE_MODEL="$JUDGE_MODEL" GISUN_JUDGE_BASE_URL=http://localhost:8002/v1
else
    serve "$MODEL" 8001 0.90
fi

export GISUN_BACKEND=openai_compat GISUN_BASE_URL=http://localhost:8001/v1 GISUN_MODEL="$MODEL" GISUN_PARALLEL=8
for MODE in ${MODES:-full}; do
    python .claude/skills/gisun-chatgpt-test/scripts/analyze.py $DATA --mode "$MODE"
done
[ "${RULES:-1}" = "1" ] && python .claude/skills/gisun-chatgpt-test/scripts/analyze.py $DATA --mode rules_only   # RULES=0 to skip the baseline
kill $PIDS
