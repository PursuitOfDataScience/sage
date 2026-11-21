# Mathematica

[Mathematica](https://www.wolfram.com/mathematica/) is powerful and intuitive computation software. It is capable of geometric, audio, graphical, and raw data analysis. The embedded Wolfram Language is an incredibly powerful scripting tool for symbolic math analysis and provides command-line-style access to the plethora of algorithms within the software. Mathematica can be used through either a GUI or a CLI.

Keywords: `symbolic math`, `computer algebra`, `Wolfram Language`, `data analysis`

## Available modules

You can check the available Mathematica versions with:

```bash
module avail mathematica
```

On Midway3, this gives:

```
---------------------------- /software/modulefiles -----------------------------
mathematica/12.3(default)  mathematica/13.0  mathematica/13.1
```

Load a specific version with, for example:

```bash
module load mathematica/12.3
```

We recommend always specifying the version so that your results are not affected if the default version changes.

## Interactive use

### Graphical interface

To use Mathematica’s GUI on Midway, we recommend connecting to Midway via [ThinLinc](../../connection/thinlinc/main.md). 

Note that once connected via ThinLinc, you will be accessing a Midway login node. To run Mathematica with its GUI on a compute node, open a terminal in the ThinLinc desktop and issue the [`sinteractive`](../../slurm/sinteractive.md) command. This will take you to a compute node. From there, you can launch Mathematica with the commands:

```bash
module load mathematica/12.3
mathematica
```

### Command-line interface

Once a Mathematica software module has been loaded, Mathematica’s command-line interface can be started with the command `math`:

```bash
$ module load mathematica/12.3
$ math
Mathematica 8.0 for Linux x86 (64-bit)
Copyright 1988-2011 Wolfram Research, Inc.

In[1]:= a=1;

In[2]:= b=2;

In[3]:= a+b

Out[3]= 3

In[4]:= Quit[];
```

More information about using Mathematica's command-line interface is available in the [Wolfram documentation](https://reference.wolfram.com/language/tutorial/UsingATextBasedInterface.html).

## Example job scripts

### Serial job

To submit Mathematica jobs to Slurm, the Mathematica commands to be executed must be contained in a single `.m` script, which is then passed to the `math` command in an sbatch file. For example, `math-simple.m` is a basic Mathematica script that computes the sum of A and B:

```mathematica
A = Sum[i, {i,1,100}]
B = Mean[{25, 36, 22, 16, 8, 42}]
Answer = A + B
Quit[];
```

This script can be submitted to Slurm with `math-simple.sbatch`, which will send the job to a compute node:

```bash
#!/bin/bash
#SBATCH --job-name=math-simple
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=00:05:00
#SBATCH --ntasks=1
#SBATCH --output=math-simple.out
#SBATCH --error=math-simple.err

module load mathematica/12.3

math -run < math-simple.m
```

Place both files in a directory on Midway, then submit the job with:

```bash
sbatch math-simple.sbatch
```

Output from this example can be found in the file `math-simple.out`, which will be created in the same directory.

### Parallel job

Mathematica can be run in parallel using the built-in `Parallel` commands or the parallel API. Parallel Mathematica jobs are limited to one node but can utilize all CPU cores on the node if allocated. Either a parallel Mathematica script must be submitted to a node that was requested with the `--exclusive` flag, or the script must specify the number of processors allocated. As an example of the latter, the following Mathematica script is appropriate for a Slurm request of 1 node with 8 tasks per node.

Batch script:

```bash
#!/bin/bash
#SBATCH --job-name=mathematica_example
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --output=mathematica_example.out
#SBATCH --error=mathematica_example.err

module load mathematica/12.3

math -run < ./sample-parallel.m
```

Mathematica script (`sample-parallel.m`):

```mathematica
(*Limits Mathematica to requested resources*)
Unprotect[$ProcessorCount];$ProcessorCount = 8;
 
(*Prints the machine name that each kernel is running on*)
Print[ParallelEvaluate[$MachineName]];

(*Prints all Mersenne prime exponents less than 2000*)
Print[Parallelize[Select[Range[2000],PrimeQ[2^#-1]&]]];
```

## Getting help

- Official documentation: [Wolfram Language & System documentation](https://reference.wolfram.com/language/){:target='_blank'}
- Built-in help: `?FunctionName` within Mathematica
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
