# CUDA-Q

[CUDA-Q](https://nvidia.github.io/cuda-quantum/latest/index.html) is a software development kit for quantum computing from NVIDIA. Additional training materials can also be found at [CUDA-Q Academic](https://github.com/NVIDIA/cuda-q-academic).

Keywords: `quantum computing`, `quantum simulation`, `GPU`, `Python`, `C++`

## Available modules

CUDA-Q is available on Midway3 as a Singularity image file (which has both the C++ and Python versions) and also as a separate Python environment via the software module `cudaq`. As with other software packages, computations with CUDA-Q should be run on the compute nodes, which can be accessed via [interactive sessions](../../slurm/sinteractive.md) or [batch jobs](../../slurm/sbatch.md).

The paths to the Singularity file and the Python environment can be obtained from the module details via the following command:

```default
module show cudaq
```

The Python environment is available at `CUDAQ_ENV` and the Singularity file at `CUDAQ_SIF`. The Python environment can be activated using `source $CUDAQ_ENV` after loading the module with `module load cudaq/`.

## Usage

To use the Singularity file for CUDA-Q, load the Singularity module using `module load singularity/`. Then, you can either use the Singularity shell or execute the program directly. Instructions on using Singularity on Midway3 can be found on the [Apptainer & Singularity](singularity.md) page.

For the first approach, launch the Singularity shell using `singularity shell $CUDAQ_SIF`, and then run a Python program, e.g., using `python example_program.py`, or a C++ program by compiling the code first, e.g., using `nvq++ example_program.cpp -o example.out`, and then executing it, e.g., using `./example.out`. 

For the second approach, execute the Python or C++ program using the `exec` command, e.g., `singularity exec $CUDAQ_SIF python example_program.py > example_output.txt` for a Python program.

When using NVIDIA GPU resources, add the `--nv` option to the `singularity` command, e.g., when launching the Singularity shell, use `singularity shell --nv $CUDAQ_SIF`.

## Example job scripts

An example batch script for running CUDA-Q jobs on GPU nodes is given below:

```default
#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:1
#SBATCH --account=pi-[cnetid]
#SBATCH --time=01:00:00
#SBATCH --partition=gpu
#SBATCH --job-name=cudaq_job
#SBATCH --output=output-%J.txt
#SBATCH --error=error-%J.txt

module load singularity/
module load cudaq/

# Run the Python program using CUDA-Q in the Singularity file
singularity exec --nv $CUDAQ_SIF python my_quantum_program.py
```

## Getting help

- Official documentation: [CUDA-Q documentation](https://nvidia.github.io/cuda-quantum/latest/index.html){:target='_blank'} and [CUDA-Q Academic](https://github.com/NVIDIA/cuda-q-academic){:target='_blank'}
- Built-in help: `module show cudaq`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
