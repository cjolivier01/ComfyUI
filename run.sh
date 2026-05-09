#!/bin/bash
export COMFY_KITCHEN_SKIP_CUBLASLT_PRELOAD=1
unset COMFYUI_DISABLE_COMFY_KITCHEN
python main.py --use-flash-attention --listen 0.0.0.0 "$@"
