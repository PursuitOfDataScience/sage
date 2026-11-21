# Perl

[Perl](https://www.perl.org/) is a general-purpose scripting language widely used for text processing, system administration, and bioinformatics pipelines.

Keywords: `scripting`, `text processing`, `bioinformatics`, `CPAN`

## Available modules

Perl is available as a software module. You can check the available versions with:

```default
module avail perl
```

On Midway3, this gives:

```
---------------------------- /software/modulefiles -----------------------------
perl/5.34.0  perl/5.40.2(default)
```

## Installing Perl modules

No additional Perl modules have been installed. Installing local modules using `local::lib` with `cpanm` is the
preferred method. Here is an example to install and test `Math::CDF`:

```default
module load perl/5.40.2
eval $(perl -I$HOME/perl5/lib/perl5 -Mlocal::lib)
cpanm Math::CDF
perl -e "require Math::CDF"
```

To have the appropriate environment available during login, it is recommended
to put these lines in your `$HOME/.bashrc`:

```default
module load perl/5.40.2
[ $SHLVL -eq 1 ] && eval "$(perl -I$HOME/perl5/lib/perl5 -Mlocal::lib)"
```

## Example job scripts

An example batch script to run a Perl script that uses modules installed with `local::lib`:

```bash
#!/bin/bash
#SBATCH --job-name=perl-job
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --mem=4G

module load perl/5.40.2
eval "$(perl -I$HOME/perl5/lib/perl5 -Mlocal::lib)"

cd $SLURM_SUBMIT_DIR

perl my_script.pl input.txt > output.txt
```

## Getting help

- Official documentation: [Perl documentation](https://perldoc.perl.org/){:target='_blank'} and [local::lib documentation](https://metacpan.org/pod/local::lib){:target='_blank'}
- Built-in help: `perldoc <Module::Name>` and `cpanm --help`
- RCC support: [contact our Help Desk](https://rcc.uchicago.edu/support-and-services/consulting-and-technical-support){:target='_blank'}
- AI assistants: an AI assistant such as Claude can help you interpret errors and adapt the job scripts on this page. See [Getting help with AI assistants](../index.md#getting-help-with-ai-assistants) for what to include in your question and what not to share.
