"""Pinned source archives used by both discovery and installation."""
TRAIN_COMMIT="372bc94bf8d90f3379b445bc08250b4a2af29af2"
COMFY_COMMIT="63be2f9b82ad0dac88a7ceaa28a9cf3154125a18"
ENGINE_SHA256 = {
    ("amenorira/lora-scripts-anima", TRAIN_COMMIT): "a1b6a5e5590bb4d11cdcdba06fc3a172b4eb18c0b49a18e0afe79a549f2fa229",
    ("comfyanonymous/ComfyUI", COMFY_COMMIT): "e0b4b5ea7182b953787aaea5263af5365ec7616c0a56b14ab1dcc2f6e6b2e747",
    ("ggml-org/llama.cpp", "b11900"): "5be8dce16b23c18320d3c6d4e43ae08bd5ae5547b7f9dd8c8e2afc531d7babb6",
}

def managed_path(components, name, repo, revision):
    return components / name / ENGINE_SHA256[(repo, revision)][:16]
