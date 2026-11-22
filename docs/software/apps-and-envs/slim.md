# SLiM

[SLiM](https://messerlab.org/slim/) (Selection on Linked Mutations) is a forward-time population genetic simulation framework developed by the Messer Lab. It uses the Eidos scripting language to define complex evolutionary scenarios including natural selection, demographic history, spatial structure, and quantitative traits. SLiM is widely used in evolutionary biology, population genetics, and ecological genetics research.

Keywords: `evolutionary biology`, `population genetics`, `forward simulation`, `Eidos`

## Available modules

SLiM is available on Midway3 with both a command-line interface (CLI) and a graphical interface (GUI). To see the available SLiM modules, run:

```
module avail SLiM
```

Modules named `SLiM/<version>` provide the `slim` and `eidos` command-line programs, and modules with the `-gui` suffix (for example, `SLiM/5.2-gui`) also provide the SLiMgui graphical interface. The examples on this page use `SLiM/5.2` and `SLiM/5.2-gui`. Running `module load SLiM` without a version loads the default module, marked `(default)` in the `module avail` output, which is not necessarily the newest release, so specify the version explicitly if your scripts rely on features of a particular SLiM version. To see what a module sets up, run:

```
module show SLiM/5.2
```

The SLiM modules have no dependencies on other modules; they only add the SLiM binaries to your `PATH`. Only one SLiM module can be loaded at a time, so run `module unload SLiM` before switching between versions or between the CLI and GUI modules.

## Interactive use

As with other software packages, SLiM simulations should be run on the compute nodes, which can be accessed via [interactive sessions](../../slurm/sinteractive.md) or [batch jobs](../../slurm/sbatch.md).

### Command-line interface

In an interactive session, load the CLI module and verify the installation:

```bash
module load SLiM/5.2
slim -v
eidos -v
```

SLiM simulations are defined in `.slim` script files written in the Eidos language. A minimal neutral evolution example `neutral_drift.slim` is given below:

```slim
// neutral_drift.slim — Wright-Fisher neutral evolution
initialize() {
    initializeMutationRate(1e-7);
    initializeMutationType("m1", 0.5, "f", 0.0);
    initializeGenomicElementType("g1", m1, 1.0);
    initializeGenomicElement(g1, 0, 99999);
    initializeRecombinationRate(1e-8);
}
1 early() {
    sim.addSubpop("p1", 500);
}
10000 late() {
    sim.outputFull();
}
```

Run the script with

```bash
slim neutral_drift.slim
```

The Eidos interpreter (`eidos`) can also be used interactively or to run standalone Eidos scripts:

```bash
eidos my_script.eidosscript
```

### Using SLiMgui on Midway3 (graphical interface)

SLiMgui provides a point-and-click environment for writing, running, and visualizing SLiM simulations. It requires a graphical desktop session and is only available on Midway3 via `SLiM/5.2-gui`.

1. Connect to Midway3 via [ThinLinc](../../connection/thinlinc/main.md).
2. Open a terminal in the ThinLinc desktop and start an interactive session on a compute node:
    ```bash
    sinteractive --account=pi-[cnetid] --partition=caslake --mem=8G --time=02:00:00
    ```
3. Load the GUI module and launch SLiMgui:
    ```bash
    module load SLiM/5.2-gui
    SLiMgui
    ```

## Example job script (Midway3)

Each SLiM simulation runs single-threaded. To run many independent replicate simulations in parallel, submit a job array. An example batch script to run 50 replicates of `neutral_drift.slim` on Midway3 is given below:

```bash
#!/bin/bash
#SBATCH --job-name=slim-run
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --array=1-50
#SBATCH --output=slim_%A_%a.out

module load SLiM/5.2

cd $SLURM_SUBMIT_DIR

slim -d REP=$SLURM_ARRAY_TASK_ID neutral_drift.slim
```

where `-d REP=$SLURM_ARRAY_TASK_ID` passes the replicate index as a constant into the script, which can be used to set the random seed or label output files:

```slim
initialize() {
    setSeed(REP);
    // ...
}
```

## Getting help

- Official documentation: [SLiM manual and resources](https://messerlab.org/slim/){:target='_blank'}
- Built-in help: `slim -h` or `module help SLiM/5.2`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
