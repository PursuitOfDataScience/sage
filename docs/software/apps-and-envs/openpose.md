# OpenPose

[OpenPose](https://github.com/CMU-Perceptual-Computing-Lab/openpose) is a real-time multi-person system to jointly detect human body, hand, facial, and foot keypoints in images and videos.

Keywords: `computer vision`, `pose estimation`, `deep learning`, `GPU`, `containers`

## Available modules

OpenPose is available on Midway3 as a container rather than a module. You can find the Singularity image file, named `openpose-v2_v0.1.sif`, under the directory `/project/rcc/shared/container`. The container is run with the `apptainer` module (see [Apptainer & Singularity](singularity.md)).

## Interactive use

To get started with a minimal working example, start an [interactive session](../../slurm/sinteractive.md) on a GPU node on Midway3, then run the following commands.

Go to your Midway3 scratch or project directory: 

`cd /scratch/midway3/$USER/containers`

or

`cd /project/drpepper/containers`

Copy the OpenPose container to your Midway3 scratch or project directory:

`cp /project/rcc/shared/container/openpose-v2_v0.1.sif ./`

Load the `apptainer` module:

`module load apptainer`

Then start a shell in the OpenPose container: 

`apptainer shell -B /project -B /scratch --nv ./openpose-v2_v0.1.sif`

After entering the container, create a directory for your results:

`mkdir -p /scratch/midway3/$USER/poses`
 
Next, navigate to the OpenPose folder and run the example:

`cd /openpose`

```
./build/examples/openpose/openpose.bin --video examples/media/video.avi --write_video /scratch/midway3/$USER/result.avi --write_json /scratch/midway3/$USER/poses --display 0
```

Once the process is complete, check the `result.avi` file created in your scratch folder.

## Example job scripts

The same example can be run as a batch job on a GPU node, using `apptainer exec` instead of an interactive shell:

```bash
#!/bin/bash
#SBATCH --job-name=openpose
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4

module load apptainer

SIF=/scratch/midway3/$USER/containers/openpose-v2_v0.1.sif
mkdir -p /scratch/midway3/$USER/poses

apptainer exec -B /project -B /scratch --nv $SIF bash -c \
  "cd /openpose && ./build/examples/openpose/openpose.bin \
     --video examples/media/video.avi \
     --write_video /scratch/midway3/$USER/result.avi \
     --write_json /scratch/midway3/$USER/poses \
     --display 0"
```

To process your own videos or images, replace `--video` with the path to your input (e.g., `--video /project/drpepper/videos/my_video.mp4`, or `--image_dir <folder>` for images).

## Getting help

- Official documentation: [OpenPose documentation](https://github.com/CMU-Perceptual-Computing-Lab/openpose/tree/master/doc){:target='_blank'}
- Built-in help: `./build/examples/openpose/openpose.bin --help` inside the container
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
