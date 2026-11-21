# Spark

[Apache Spark](https://spark.apache.org/) is a fast and general engine for large-scale data processing. It
has Scala, Java, and Python APIs and can be run on either a single node
or multiple nodes. In both cases, it is recommended to have exclusive
access to the node(s) in Slurm.

Keywords: `big data`, `data processing`, `distributed computing`, `Scala`, `PySpark`

## Available modules

You can check the available Spark versions with:

```bash
module avail spark
```

On Midway3, this gives:

```
---------------------------- /software/modulefiles -----------------------------
spark/3.3.2(default)
```

## Example job scripts

### Single node

Here are the SparkPi and `pi.py` examples from the Spark distribution running on
a single node (sbatch script `spark-single-node.sbatch`):

```bash
#!/bin/bash
#SBATCH --job-name=spark
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
# Exclusive mode is recommended for all spark jobs
#SBATCH --exclusive
#SBATCH --nodes=1
#SBATCH --time=10

module load spark/3.3.2

# This syntax tells spark to use all cpu cores on the node.
export MASTER="local[*]"

# This is a scala example
run-example SparkPi

# This is a python example. 
# For production jobs, you'll probably want to have a python module loaded.
# This will use the system python if you don't have a python module loaded.
spark-submit --master $MASTER $SPARK_HOME/examples/src/main/python/pi.py
```

### Multiple nodes

For multi-node Spark jobs, a helper script is provided to launch the master
and worker tasks in the Slurm allocation. Here are the same examples as above,
but with Spark running on multiple nodes (sbatch script `spark-multi-node.sbatch`):

```bash
#!/bin/bash
#SBATCH --job-name=spark-multi-node
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
# Exclusive mode is recommended for all spark jobs
#SBATCH --exclusive
#SBATCH --nodes=4
#SBATCH --time=10

module load spark/3.3.2

# This command starts the spark workers on the allocated nodes
start-spark-slurm.sh

# This syntax tells the spark workers where the master is
export MASTER=spark://$HOSTNAME:7077

# This is a scala example
run-example SparkPi

# This is a python example.
# For production jobs, you'll probably want to have a python module loaded.
# This will use the system python if you don't have a python module loaded.
spark-submit --master $MASTER $SPARK_HOME/examples/src/main/python/pi.py
```

## Getting help

- Official documentation: [Apache Spark documentation](https://spark.apache.org/docs/latest/){:target='_blank'}
- Built-in help: `spark-submit --help`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
