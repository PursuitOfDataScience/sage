# Stata

[Stata](https://www.stata.com/) is a powerful statistical software package that is widely used in scientific computing. RCC users are licensed to use Stata on all RCC resources. Stata can be used interactively or as a submitted script. Please note that if you would like to run it interactively, you must still run it on a compute node to keep the login nodes free for other users. Stata/MP can run in parallel on up to 16 cores.

Keywords: `statistics`, `econometrics`, `data analysis`, `social sciences`

**NOTE**: Stata examples in this document are adapted from a Princeton [tutorial](http://data.princeton.edu/stata/). You may find it useful if you are new to Stata or want a refresher.

## Available modules

You can check the available Stata versions with:

```bash
module avail stata
```

On Midway3, this gives:

```
---------------------------- /software/modulefiles -----------------------------
stata/16(default)  stata/18  stata/19
```

## Interactive use

### Graphical interface

If you need to use the Stata GUI, connect to Midway with [ThinLinc](../../connection/thinlinc/main.md).

Obtain an [interactive session](../../slurm/sinteractive.md) on a compute node. This is necessary so that your computation doesn’t interrupt other users on the login node. Now, load Stata:

```bash
sinteractive --account=pi-[cnetid] --partition=caslake --time=02:00:00
module load stata/19
xstata
```

This will open up a Stata window. The middle pane has a text box to enter commands at the bottom, and a box for command results on top. On the left there’s a box called “Review” that shows your command history. The right-hand box contains information about variables in the currently loaded data set.

One way Stata can be used is as a fancy desktop calculator. Type the following code into the command box:

```default
display 2+2
```

Stata can do much more if data is loaded into it. The following code loads census data that ships with Stata, prints a description of the data, then creates a graph of life expectancy over GNP:

```default
sysuse lifeexp
describe
graph twoway scatter lexp gnppc
```

### Command-line interface

This is very similar to running graphically; the command-line interface is equivalent to the “Results” pane in the graphical interface. Again, please use a compute node if you are running computationally intensive calculations:

```bash
sinteractive --account=pi-[cnetid] --partition=caslake --time=02:00:00
module load stata/19
stata
```

## Example job scripts

### Serial job

A Stata script is called a “do-file,” which contains a list of Stata commands that the interpreter will execute. You can write a do-file in any text editor, or in the Stata GUI’s do-file editor: click “Do-File Editor” in the “Window” menu. If your do-file is named `example.do`, you can run it with either of the following commands:

```bash
stata < example.do
stata -b do example.do
```

Here is a very simple do-file, `stata_example.do`, which computes a regression on the sample data set from above:

```default
version 19 // Stata version the do-file was written for; optional but recommended

sysuse lifeexp
gen loggnppc = log(gnppc)
regress lexp loggnppc
```

Here is a submission script, `stata_example.sbatch`, that runs the do-file on a compute node:

```bash
#!/bin/bash
#SBATCH --job-name=stataEx
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --output=stata_example.out
#SBATCH --error=stata_example.err

module load stata/19

stata -b do stata_example.do
```

Place both files in a directory on Midway, then submit the job with:

```bash
sbatch stata_example.sbatch
```

Output from this example can be found in the file `stata_example.log`, which will be created automatically in your current directory.

### Parallel job with Stata/MP

The parallel version of Stata, Stata/MP, can speed up computations and make effective use of RCC’s resources. When running Stata/MP, you are limited to 16 cores and 5000 variables. To run an interactive Stata/MP session:

```bash
sinteractive --account=pi-[cnetid] --partition=caslake --cpus-per-task=16 --time=02:00:00
module load stata/19
stata-mp
# or, for the graphical interface:
xstata-mp
```

Here is a sample do-file, `stata_parallel.do`, that would benefit from parallelization. It runs bootstrap estimation on another data set that ships with Stata:

```default
version 19

sysuse auto
expand 10000
bootstrap: logistic foreign price-gear_ratio
```

Here is a submission script, `stata_parallel.sbatch`, that runs the above do-file with Stata/MP:

```bash
#!/bin/bash
#SBATCH --job-name=stataMP
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=16
#SBATCH --output=stata_parallel.out
#SBATCH --error=stata_parallel.err

module load stata/19

stata-mp -b do stata_parallel.do
```

Submit the job with:

```bash
sbatch stata_parallel.sbatch
```

## Getting help

- Official documentation: [Stata documentation](https://www.stata.com/features/documentation/){:target='_blank'}
- Built-in help: `help <command>` within Stata
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
