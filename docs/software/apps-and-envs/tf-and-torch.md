# TensorFlow and PyTorch

[TensorFlow](https://www.tensorflow.org/) and [PyTorch](https://pytorch.org/) are open-source deep learning frameworks for building and training neural networks on CPUs and GPUs.

Keywords: `deep learning`, `machine learning`, `neural networks`, `GPU`, `Python`

## Available modules

To use TensorFlow or PyTorch on Midway's GPU nodes, you may use an existing installation of either package provided as a module (e.g., `module load tensorflow`) or a conda environment (e.g., the `ml` environment of `python/miniforge-25.3.0`; see the [Python](python.md) page), or install them into your own personal environment. You can check the available modules with `module avail tensorflow`, `module avail pytorch`, and `module avail cuda`.

Importantly, you must use
 an existing installation of CUDA and/or cuDNN, which you will first load via `module load cuda/<version>` or `module load cudnn/<version>` (which automatically loads cuda).

!!! note "Versions, versions, versions"
    As of March 2023, we find the combination of module versions `python/anaconda-2021.05`, `cuda/11.2`, and `cudnn/11.2` to be the most stable. If you wish to use newer versions of Python or CUDA, be sure to check the version compatibility as a first troubleshooting step when checking GPU engagement. 

With the CUDA module(s) loaded and while connected to a GPU node, you should be able to import either TensorFlow or PyTorch and check GPU engagement with the following steps: 

## GPU Engagement
Here are a few quick tips on how to make sure you're actually using a GPU.

### Checking in terminal

Before you even run your script, it can be useful to check that GPUs are allocated to your jobs on the compute nodes.

NVIDIA has a built-in System Management Interface that makes this simple with one command:

```
nvidia-smi
```

You should see details about the device, if it is detected.


### TensorFlow
Here's how to check if TensorFlow sees your GPU(s):

```
import tensorflow as tf
```
The one-liner:

```
print("Num GPUs Available: ", len(tf.config.experimental.list_physical_devices('GPU')))
```
For more info:

```
gpus = tf.config.experimental.list_physical_devices('GPU')
tf.config.experimental.get_device_details(gpus[0])
```

### PyTorch
And here's how to check with PyTorch:

```
import torch
torch.cuda.device_count()
torch.cuda.get_device_name()
```

## Example job scripts

The following batch script runs a TensorFlow or PyTorch training script on one GPU on Midway3:

```bash
#!/bin/bash
#SBATCH --job-name=1gpu-example
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --constraint=v100
#SBATCH --time=02:00:00
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4

module load tensorflow
module load cudnn

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

# Print GPU information to the output file for troubleshooting
nvidia-smi

python training.py
```

See [GPU jobs](../../slurm/sbatch.md#gpu-jobs) for more information on requesting GPUs.

## Getting help

- Official documentation: [TensorFlow guide](https://www.tensorflow.org/guide){:target='_blank'} and [PyTorch documentation](https://pytorch.org/docs/stable/){:target='_blank'}
- Built-in help: `nvidia-smi` to check the GPUs allocated to your job
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
