# Space Ranger

[Space Ranger](https://www.10xgenomics.com/support/software/space-ranger/latest) is a set of analysis pipelines from 10x Genomics that process Visium Spatial Gene Expression data with brightfield and fluorescence microscope images. See the [Space Ranger manual](https://support.10xgenomics.com/spatial-gene-expression/software/pipelines/latest/what-is-space-ranger) for details.

Keywords: `spatial transcriptomics`, `Visium`, `gene expression`, `bioinformatics`, `10x Genomics`

## Available modules

Space Ranger is not provided as a software module. It comes as a precompiled binary that you install in your own space, as described below.

### Installation

Use Firefox in [ThinLinc](../../connection/thinlinc/main.md) to download the [software](https://www.10xgenomics.com/support/software/space-ranger/downloads). You may create a folder called `software` in your home or project directory and extract it to that location. Replace `pi-cnetid` with your group name. For personal use, you can use the scratch storage available at `$SCRATCH/$USER`.
Set the extraction location to `/project/pi-cnetid/software` (or another location) and use the following command:

```bash
tar -xzvf spaceranger-3.0.0.tar.gz --directory /project/pi-cnetid/software
```

### Updating PATH

After extracting the software, update `PATH` as follows:

```bash
export PATH=/project/pi-cnetid/software/spaceranger-3.0.0:$PATH
```

The command above changes `PATH` only for the current shell. You can permanently update `PATH` by appending the following command to your `~/.bashrc` file:

```bash
echo 'export PATH=/project/pi-cnetid/software/spaceranger-3.0.0:$PATH' >> ~/.bashrc
```

These commands ensure that `spaceranger-3.0.0` is extracted to the specified location and permanently added to `PATH`, as discussed in the [Space Ranger installation guide](https://www.10xgenomics.com/support/software/space-ranger/downloads/space-ranger-installation).

Alternatively, a Space Ranger [Docker image](https://hub.docker.com/r/cumulusprod/spaceranger/tags) can be run using [Apptainer](singularity.md).

## Example job scripts

The following batch script runs `spaceranger count` on a single node. Replace the placeholders with your own reference transcriptome, FASTQ directory, sample name, and image/slide information. The exact required arguments depend on your assay and Space Ranger version, so check the [Space Ranger tutorials](https://www.10xgenomics.com/support/software/space-ranger/latest/tutorials) and `spaceranger count --help`.

```bash
#!/bin/bash
#SBATCH --job-name=spaceranger
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G

export PATH=/project/pi-cnetid/software/spaceranger-3.0.0:$PATH

# Run in scratch; stop if the directory cannot be created or entered
RUNDIR=/scratch/midway3/$USER/spaceranger_runs
mkdir -p $RUNDIR
cd $RUNDIR || exit 1

spaceranger count --id=<sample_id> \
                  --transcriptome=<path/to/reference> \
                  --fastqs=<path/to/fastqs> \
                  --sample=<sample_name> \
                  --image=<path/to/image.tif> \
                  --slide=<slide_serial> \
                  --area=<capture_area> \
                  --create-bam=true \
                  --localcores=$SLURM_CPUS_PER_TASK \
                  --localmem=120
```

`--create-bam` is required in Space Ranger 3.0 and later; set it to `false` if you do not need BAM files, which saves considerable disk space and run time. `--localcores` and `--localmem` (in GB) keep Space Ranger within the resources requested from Slurm; set `--localmem` slightly below `--mem`. Space Ranger can also submit its pipeline stages as separate Slurm jobs; see [Job Submission Mode](https://www.10xgenomics.com/support/software/space-ranger/latest/advanced/job-submission-mode) and [Cluster Mode](https://www.10xgenomics.com/support/software/space-ranger/latest/advanced/cluster-mode).

## Getting help

- Official documentation: [Space Ranger documentation](https://www.10xgenomics.com/support/software/space-ranger/latest){:target='_blank'} and [tutorials](https://www.10xgenomics.com/support/software/space-ranger/latest/tutorials){:target='_blank'}
- Built-in help: `spaceranger --help` and `spaceranger count --help`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
