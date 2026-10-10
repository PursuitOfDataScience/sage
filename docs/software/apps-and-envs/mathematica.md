# Mathematica

Mathematica is powerful and intuitive computation software.  It is capable of geometric, audio, graphical, and raw data analysis.  The embedded Wolfram Language is an incredibly powerful scripting tool for doing symbolic math analysis and granting command line style access to the plethora of algorithms within the software.  Mathematica has a GUI and CLI that can be used.

## Getting Started

To gain access to Mathematica, a Mathematica module must be loaded with the command:

```bash
module load mathematica
```

A full list of available Mathematica versions can be obtained by calling the command:

```bash
module avail mathematica
```

## Using Mathematica’s Graphical Interface

To use Mathematica’s GUI interface on Midway, we recommend connecting to Midway via ThinLinc. 

Note that once connected via ThinLinc, you will be accessing a Midway login node.  In order to run Mathematica with its GUI interface on a compute node, obtain a terminal in the ThinLinc desktop and issue the **sinteractive** command.  This will deliver you to a compute node.  From there, you can launch Mathematica with the commands:

```bash
module load mathematica
mathematica
```

and have access to the GUI interface.

## Using Mathematica’s Textual Interface

Once a Mathematica software module has been loaded, Mathematica’s command line interface can be started with the command `math`.

```bash
$ module load mathematica
$ math
Mathematica 8.0 for Linux x86 (64-bit)
Copyright 1988-2011 Wolfram Research, Inc.

In[1]:= a=1;

In[2]:= b=2;

In[3]:= a+b

Out[3]= 3

In[4]:= Quit[];
```

More information about using the command line interface to Mathematica is available here: [http://reference.wolfram.com/language/tutorial/UsingATextBasedInterface.html](http://reference.wolfram.com/language/tutorial/UsingATextBasedInterface.html)

## Running Mathematica Jobs with SLURM

To submit Mathematica jobs to Midway’s resource scheduler, SLURM, the Mathematica commands to be executed must be contained in a single .m script.  The .m script will then be passed to the `math` command in an sbatch file.  For example:

`math-simple.m` is a basic Mathematica script that computes the sum of A and B:

```bash
A = Sum[i, {i,1,100}]
B = Mean[{25, 36, 22, 16, 8, 42}]
Answer = A + B
Quit[];
```

This script can be submitted to SLURM with `math-simple.sbatch` which will send the job to a compute node:

```bash
#!/bin/bash

#SBATCH --job-name=math-simple
#SBATCH --output=math-simple.out
#SBATCH --error=math-simple.err
#SBATCH --partition=sandyb
#SBATCH --time=00:05:00
#SBATCH --ntasks=1

module load mathematica

math -run < math-simple.m
```

To run this example, download both files to a directory on Midway.  Then, enter the following command to submit the job to the scheduler:

```bash
sbatch math-simple.sbatch
```

Output from this example can be found in the file named math-simple.out which will be created in the same directory.

## Using Multiple CPUs in Mathematica

Mathematica can be run in parallel using the built in `Parallel` commands or by utilizing parallel API.  Parallel Mathematica jobs are limited to one node, but can utilize all CPU cores on the node if allocated.  A parallel Mathematica script must either be submitted to a node that was requested with the `exclusive` flag or the script must specify the number of processors allocated.  As an example of the latter, the following Mathematica script would be appropriate for a SLURM request of 1 node with 8 tasks per node.

### Sample Parallel Job Submission

SBATCH script:

```bash
#!/bin/bash
#SBATCH --job-name=mathematica_example
#SBATCH --output=mathematica_example.out
#SBATCH --error=mathematica_example.err
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8

module load mathematica

math -run < ./sample-parallel.m
```

Mathematica script:

```bash
(*Limits Mathematica to requested resources*)
Unprotect[$ProcessorCount];$ProcessorCount = 8;
 
(*Prints the machine name that each kernel is running on*)
Print[ParallelEvaluate[$MachineName]];

(*Prints all Mersenne PRime numbers less than 2000*)
Print[Parallelize[Select[Range[2000],PrimeQ[2^#-1]&]]];
```
