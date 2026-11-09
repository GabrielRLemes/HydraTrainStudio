"""Use BF16 for the frozen SDXL base while leaving trainable LoRA parameters in FP32."""
import runpy
import torch
from pathlib import Path
from library import sdxl_train_util

if __name__=="__main__":
    original = sdxl_train_util.match_mixed_precision
    def frozen_dtype(args, weight_dtype):
        if args.network_train_unet_only and args.mixed_precision=="bf16":
            return torch.bfloat16
        return original(args,weight_dtype)
    sdxl_train_util.match_mixed_precision=frozen_dtype
    runpy.run_path(str(Path.cwd()/"sdxl_train_network.py"),run_name="__main__")

