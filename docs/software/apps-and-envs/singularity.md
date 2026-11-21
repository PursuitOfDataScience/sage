# Apptainer & Singularity

[Apptainer](https://apptainer.org/) and [Singularity](https://sylabs.io/) are widely adopted container runtimes that implement a unique security model to mitigate privilege escalation risks and provide a platform to capture a complete application environment into a single file (SIF).

Keywords: `containers`, `Docker`, `reproducibility`, `SIF`

## Available modules

Load either runtime with:

```
module load apptainer
```

or

```
module load singularity
```
Apptainer and Singularity commands are highly compatible with each other. Apptainer also provides a `singularity` command so that workflows that invoke it need no changes.

You can pull Singularity and Docker container images from external sources to your space on the login nodes:

```
singularity pull ubuntu.sif docker://ubuntu:latest
```

and execute them on the compute nodes. You can bind-mount paths on Midway into the containers at run time.

Instructions for using Singularity on Midway3 are available in the [singularity-demo repository](https://github.com/rcc-uchicago/singularity-demo).

## Example job scripts


Suppose that you have pulled the image from the Internet (e.g., Docker Hub) to your folder on Midway3.
In practice, you may want to bind-mount folders outside the container
(e.g., where your input data is located and where output data is to be stored) to paths inside the container.
The following batch script illustrates a simple use case.

```
#!/bin/bash
#SBATCH --job-name=test-singularity
#SBATCH --nodes=1
#SBATCH --time=05:00:00
#SBATCH --account=pi-<group>
#SBATCH --partition=caslake

module load singularity/3.9.2

singularity exec --bind /path/outside/image/:/path/inside/image/ \
                 --bind $PWD:/run/user \
                 your_image.sif your_script.py arg1 arg2

```
In this example, `/path/outside/image/` is the path in your Midway3 directory, e.g., `/project/[pi-cnetid]/your-folder/`,
and `/path/inside/image/` is the path inside the container, e.g., `/tmp/`. `$PWD` is the present working directory (on Midway3),
and `/run/user` is its counterpart inside the container. When executed inside the container, the Python script will read
input from `/path/inside/image` and write output to `/run/user/`.

## Known issues
By default, Singularity uses the `/tmp` directory on the local machine (whichever node or login node you are working on) to dump temporary and cache files generated during the build process. After a container is built, these are usually deleted. For containers with a large total size (more than a few GB), you may encounter the error `no space left on device`.

If you encounter this issue, it most likely means that `/tmp` filled up on the machine you're using. To get around this issue, create `faketmp` and `fakecache` directories, and redirect Singularity's default temporary output by setting `SINGULARITY_TMPDIR` and `SINGULARITY_CACHEDIR`:

```
export SINGULARITY_CACHEDIR=$SCRATCH/$USER/container/fakecache
export SINGULARITY_TMPDIR=$SCRATCH/$USER/container/faketmp
```

Apptainer builds need access to local storage rather than network storage:

```
export APPTAINER_CACHEDIR=/tmp/$USER
export APPTAINER_TMPDIR=/tmp/$USER
```

You can delete everything in the `faketmp` and `fakecache` directories after your container is created.

## Getting help

- Official documentation: [Apptainer user guide](https://apptainer.org/docs/user/latest/){:target='_blank'} and [RCC singularity-demo repository](https://github.com/rcc-uchicago/singularity-demo){:target='_blank'}
- Built-in help: `apptainer help` or `singularity help`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
