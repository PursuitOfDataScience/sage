# Modules

[Apptainer](https://apptainer.org/) and [Singularity](https://sylabs.io/) are widely-adopted container runtimes that implement a unique security model to mitigate privilege escalation risks and provides a platform to capture a complete application environment into a single file (SIF).

```
module load apptainer
```
or
```
module load singularity
```
Apptainer and Singularity commands are highly compatible with each other. Apptainer also provides a `singularity `command to ensure that no changes needed in workflows that invoke the command.

You can pull container Singularity and Docker container images from external sources to your spaces on the login nodes:
```
singularity pull ubuntu.sif docker://ubuntu:latest
```
and execute them on the compute nodes. You can bind and mount the paths on Midway to the containers at run time.

There are instructions to use Singularity on Midway3 given [here](https://github.com/rcc-uchicago/singularity-demo).

## Example job script

Suppose that you have pulled the image from the Internet (e.g. Docker Hub) to your folder on Midway3.
In practice, you may want to bind mount the folders outside the container
(e.g. where your input data is located and where output data is to be stored) with those inside the container.
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
In this example, `/path/outside/image/` is the path in your Midway3 directory, e.g. `/project/[pi-cnetid]/your-folder/`
and `/path/inside/image/` is the path inside the container, e.g. `/tmp/`. `$PWD` is the present working directory (on Midway3)
and `/run/user` is the one present inside the container. The python script when executed inside the container will read
input from `/path/inside/image` and generate output to `/run/user/`.

## Known issues
By default, Singularity uses the `/tmp` directory on the local machine (whichever node or login node you are working on) to dump temporary and cache files generated during the build process. After a container is built, these are usually deleted. For containers with a large total size (more than a few GB), you may encounter an error `no space left on device`

If you encounter this issue, then it most likely means that `/tmp` got filled up on the machine you're using. To get around this issue, create `faketmp` and `fakecache` directories, and redirect Singularity's default temporary output to `SINGULARITY_TMPDIR` and `SINGULARITY_CACHEDIR`
```
export SINGULARITY_CACHEDIR=$SCRATCH/$USER/container/fakecache
export SINGULARITY_TMPDIR=$SCRATCH/$USER/container/faketmp
```

Apptainer builds need access to local storage rather than NFS storage.
```
export APPTAINER_CACHEDIR=/tmp/$USER
export APPTAINER_TMPDIR=/tmp/$USER
```

You can delete everything in the `faketmp` and `fakecache` directories after creation of your container.
