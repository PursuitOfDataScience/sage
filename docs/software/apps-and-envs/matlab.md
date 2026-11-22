# MATLAB

[MATLAB](https://www.mathworks.com/products/matlab.html) is a numerical computing environment and programming language widely used for data analysis, signal and image processing, simulation, and algorithm development. Most MATLAB toolboxes are available through the University's license (see the [list of toolboxes](https://itservices.uchicago.edu/page/matlab-tah-toolboxes){:target='_blank'}).

Keywords: `numerical computing`, `data analysis`, `signal processing`, `image processing`, `parallel computing`

!!! warning
    Compute- and memory-intensive MATLAB jobs must run on compute nodes, not on the login nodes. Jobs running on the login nodes are subject to termination without warning by RCC system administrators.

## Available modules

You can check the available MATLAB modules via `module avail matlab`:

===+ "Midway3"
    ```
    ---------------------------- /software/modulefiles -----------------------------
    matlab/2020b  matlab/2021b  matlab/2022a  matlab/2022b  matlab/2023a(default)
    ```

To load a specific version:

```
module load matlab/2023a
```

We recommend always specifying the version so that your results are not affected if the default version changes. You can see what a module sets up with `module show matlab/2023a`.

## Interactive use

### Graphical interface

To use the MATLAB GUI, first connect to Midway3 via [ThinLinc](../../connection/thinlinc/main.md) or start a Midway3 Desktop session in [Open OnDemand](../../connection/open_ondemand/open_ondemand.md). In a ThinLinc session, open a terminal and start an [interactive session](../../slurm/sinteractive.md) on a compute node:

```
sinteractive --account=pi-[cnetid] --partition=caslake --ntasks=1 --cpus-per-task=4 --mem=16G --time=02:00:00
```

Then launch MATLAB:

```
module load matlab/2023a
matlab
```

### Command-line interface

In an interactive session, you can also run MATLAB without the GUI:

```
module load matlab/2023a
matlab -nodisplay
```

## Example job scripts

### Serial job

To run MATLAB in a batch job, put your MATLAB commands in a script file. For example, `matlab_simple.m` computes and prints a 10x10 magic square:

```matlab
% matlab_simple.m
M = magic(10);
disp(M)
fprintf('Sum of each column: %d\n', sum(M(:,1)));
```

The following batch script, `matlab_simple.sbatch`, runs it on a compute node:

```bash
#!/bin/bash
#SBATCH --job-name=matlab-simple
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --output=matlab_simple.out
#SBATCH --error=matlab_simple.err

module load matlab/2023a

cd $SLURM_SUBMIT_DIR

matlab -batch "matlab_simple"
```

Submit the job with:

```
sbatch matlab_simple.sbatch
```

The output will be written to `matlab_simple.out` in the same directory. The `-batch` option runs the script non-interactively without the desktop and exits MATLAB when the script finishes (or with a non-zero exit code if it fails). Pass the script name without the `.m` extension.

### Parallel job with `parfor`

MATLAB parallel jobs use the Parallel Computing Toolbox (PCT) with a local pool of workers on a **single node**. The iterations of a `parfor` loop are distributed to the workers in the pool, so each iteration must be independent of the others. Request the number of workers with `--cpus-per-task` and use it to size the pool:

```matlab
% matlab_parfor.m
nworkers = str2double(getenv('SLURM_CPUS_PER_TASK'));
pc = parcluster('local');
parpool(pc, nworkers);

results = zeros(1, 100);
parfor i = 1:100
    results(i) = sum(svd(rand(200)));
end
disp(mean(results))

delete(gcp('nocreate'));
```

```bash
#!/bin/bash
#SBATCH --job-name=matlab-parfor
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --output=matlab_parfor.out
#SBATCH --error=matlab_parfor.err

module load matlab/2023a

cd $SLURM_SUBMIT_DIR

matlab -batch "matlab_parfor"
```

!!! note
    RCC does not provide MATLAB Parallel Server (formerly MATLAB Distributed Computing Server, MDCS), so a MATLAB parallel pool cannot span multiple nodes. To use more than one node, split your work into independent jobs, e.g., with a [job array](../../slurm/sbatch.md#job-arrays).

### Running multiple parallel jobs at the same time

When several PCT jobs run at the same time, they all use the same default "Job Storage Location" (`~/.matlab/`) to coordinate their pools. The jobs can then overwrite each other's files, causing errors or early termination. To avoid this, give each job its own job storage location:

```matlab
% matlab_multi.m
pc = parcluster('local');
pc.JobStorageLocation = getenv('MATLAB_JOB_STORAGE');
parpool(pc, str2double(getenv('SLURM_CPUS_PER_TASK')));
parfor i = 1:100
    ones(10, 10);
end

delete(gcp('nocreate'));
```

```bash
#!/bin/bash
#SBATCH --job-name=matlab-multi
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --output=matlab_multi_%j.out
#SBATCH --error=matlab_multi_%j.err

module load matlab/2023a

cd $SLURM_SUBMIT_DIR

# Create a job-specific storage location for the parallel pool
export MATLAB_JOB_STORAGE=/scratch/midway3/$USER/matlab_jobs/$SLURM_JOB_ID
mkdir -p $MATLAB_JOB_STORAGE

matlab -batch "matlab_multi"

# Clean up
rm -rf $MATLAB_JOB_STORAGE
```

## Getting help

- Official documentation: [MATLAB documentation](https://www.mathworks.com/help/matlab/){:target='_blank'} and [Parallel Computing Toolbox documentation](https://www.mathworks.com/help/parallel-computing/){:target='_blank'}
- Built-in help: `help <function>` or `doc <function>` within MATLAB, and `module help matlab/2023a`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
