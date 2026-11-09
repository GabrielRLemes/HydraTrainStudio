<div align="center">
  <img src="HydraTrainStudio_Assets/branding/hydra_lockup_compact.png" width="420" alt="HydraTrainStudio">
  <p><strong>Collect media. Review your dataset. Train and compare your LoRAs.</strong></p>
  <p>A guided local workflow for Krea 2, Anima and Illustrious.</p>
  <p><a href="https://github.com/GabrielRLemes/HydraTrainStudio/releases"><b>Download for Windows or Linux</b></a> · <a href="#your-first-project">Getting started</a> · <a href="#upcoming-updates">Upcoming updates</a></p>
</div>

![HydraTrainStudio home screen](docs/inicio.png)

## What makes HydraTrainStudio different

**HydraTrainStudio connects media collection, dataset preparation, approval, training and checkpoint comparison in one application.** Its focus is the work that takes an image from a download or local folder to an approved training sample, then helps you inspect the resulting LoRA versions.

**Search and download or import → Extract video frames → Review crops, tags and captions → Approve the dataset → Train → Compare checkpoints**

- **Start with your media.** Search supported sites, import local images and videos, and extract frames within the same project.
- **Review what will reach the trainer.** Inspect the image preview, adjust the crop, edit tags and captions, and approve samples for the selected model profile and target resolution.
- **Keep captioning connected to review.** Generate or improve captions using the image, tags and your edited text. Apply actions to selected items or regenerate captions and tags across the project.
- **Move from approval to training.** Use the automatic settings or open advanced controls for epochs, rank, alpha, batch size, gradient accumulation and more.
- **Compare the versions you trained.** Generate checkpoint grids with shared prompts and seeds, mark favorites, retest them with another seed, and resume an incomplete comparison.

HydraTrainStudio integrates established training engines, including sd-scripts and musubi-tuner through lora-scripts-anima, with ComfyUI for test generation. These projects are credited in [Third-party components](THIRD_PARTY.md).

## Installation

| Platform | First launch | Open it again |
|---|---|---|
| Windows x64 | Download and run **HydraTrainStudio-Windows.exe** from a release. | Use the Start menu or open **HydraTrainStudio.exe** in `%LOCALAPPDATA%\HydraTrainStudio`. |
| Linux x86-64 · experimental | Download **HydraTrainStudio-Linux.sh** and run `bash HydraTrainStudio-Linux.sh` from the download folder. | Use the application menu or run `bash "${XDG_DATA_HOME:-$HOME/.local/share}/HydraTrainStudio/abrir-linux.sh"`. |

The launcher downloads the release package, verifies its SHA-256 checksum, installs the interface and integration code, and opens the app. On the first launch, the component wizard lets you select the training families, **Caption** for local vision and **ComfyUI** for test generation. You can reopen it from the Components section in Settings.

Local training requires an **NVIDIA GPU with CUDA**. The original installation used an RTX 3060 with 12 GB of VRAM and 32 GB of system RAM. Calibrate the preset on the computer you will use. Check the space estimate before downloading weights. Custom model URLs require additional space beyond the displayed total.

**Linux requirements:** a graphical desktop, an NVIDIA driver compatible with the CUDA 13 stack, Python 3.11 or newer with Tk and venv, curl and unzip. Building llama.cpp requires CMake and a C++ compiler, plus nvcc for CUDA acceleration. An existing `llama-server` on PATH can also be used. Saved credentials use the desktop's Secret Service keyring. Full installation and training validation on physical Linux GPUs remains planned.

## Your first project

1. In **Settings**, choose the model family, calibrate the resolution and configure the vision service.
2. In **Media**, import files, search supported sites or extract video frames.
3. In **Review**, inspect thumbnails, adjust crops and edit tags and captions. Run actions on a selection or across the project, then approve the samples for training.
4. In **Training and testing**, choose **Automatic** or adjust epochs, rank, alpha, batch size, gradient accumulation, optimizer and learning-rate schedule in **Advanced** mode.
5. Compare checkpoints using the same prompts and seeds. Mark favorites, retest with another seed or resume an incomplete grid.

The app offers Portuguese, English, Spanish and Simplified Chinese. Translation coverage is still partial.

## Model choices

| Purpose | Available choices |
|---|---|
| **Training** | Krea 2 uses the Raw base, Anima uses Anima Base, and Illustrious uses Illustrious XL v0.1. Training profiles fix the model files, and the installer verifies the distributed weights against the manifest hashes. |
| **Vision and captions** | Install the default GGUF pair, select a local vision GGUF and its matching projector, or provide direct Hugging Face URLs for both files. You can also configure an existing vision service. |
| **LoRA testing** | Use the family's default base or select a compatible file through **Test and compare → Choose test base**. The component wizard can download a custom test base by URL. Each comparison records its selected base for later resumes and retests. |

## More tools

- **Dataset import** · Import projects, databases, manifests and media with adjacent TXT files. Review thumbnails with multiple selection, approval and batch actions.
- **Caption prompts** · Create named prompts for vision analysis and edit captions before training.
- **LoRA merging** · Combine two or more compatible LoRAs, adjust their individual weights and save a new file.
- **Appearance** · Choose a light or dark theme and adjust the font size.

## Upcoming updates

We plan to build on the guided workflow with the following features. These are roadmap items, with release dates to be announced.

| Planned feature | What it will help you do |
|---|---|
| **Expanded checkpoint comparator** | Inspect two checkpoints side by side with synchronized zoom, switch between seeds and compare LoRA strengths. |
| **More complete batch tag editor** | Find and replace tags, remove tags across a selection, standardize terms and undo batch edits. |
| **Goal-based preparation** | Choose a training goal such as style, character, object or clothing, then receive captioning guidance and suggested tests tailored to that goal. |
| **More search and download sources** | Collect media from additional supported sites through the existing search, download and review workflow. |

We also plan to validate clean installations on Windows and Linux GPUs, expand test-model compatibility information and complete translation coverage.

## Feedback and contributing

Tell us your operating system, GPU, model family and the step where an issue occurred. Remove API keys and personal paths before attaching logs. Feature suggestions and reports from real training projects are welcome. [Open an issue](https://github.com/GabrielRLemes/HydraTrainStudio/issues)

Original code is released under the [MIT license](LICENSE). Models and training engines are downloaded from their respective projects and retain their own terms. [Third-party components and credits](THIRD_PARTY.md) · [Release build instructions, in Portuguese](docs/PUBLICAR.md)
