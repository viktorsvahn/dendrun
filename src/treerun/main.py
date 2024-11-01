#!/usr/bin/python

import sys
import os
import argparse
#import json
import yaml
import subprocess
import copy
import datetime
from pathlib import Path

import itertools
import functools
#import collections

from importlib.metadata import version


description = """
Treerun is a CLI for running teriminal commands from all subdirectories in an
existing tree structure.

The purpose of this software is to be able to run terminal commands from sub-
directories in a tree structure. Each node (sub-directory) must contain the
same subdirectories as its neighbour within a level so that the number of
splits is constant over each level.

The input is YAML-based and should contain a `Tree`-block and a `Modes`-block.
The former defines the tree structure of all directories by including sub-
blocks that contain the directories within that level and the latter is used to
the define available commands (use --example to see an example).
"""

example_tree = """Example tree structure:
---
root-dir                    <-- arbitrary root directory
├── input.yaml              <-- input file must be in root-dir
├── dir1
│   ├── subdir1
│   │   ├── subsubdir1
│   │   │   ├── run.sh
│   │   │   └── test-mod    <-- mod is whatever follows the --modifier flag
│   │   │       └── run.sh
│   │   ├── subsubdir2
│   │   │   ├── run.sh
│   │   │   └── test-mod
│   │   │       └── run.sh
│   │   └── subsubdir3
│   │       ├── run.sh
│   │       └── test-mod
│   │           └── run.sh
│   └── subdir2
│       ├── subsubdir1
│       │   ├── run.sh
│       │   └── test-mod
│       │       └── run.sh
│       ├── subsubdir2
│       │   ├── run.sh
│       │   └── test-mod
│       │       └── run.sh
│       └── subsubdir3
│           ├── run.sh
│           └── test-mod
│               └── run.sh
└── dir2
    ├── subdir1
    │   ├── subsubdir1
    │   │   ├── run.sh
    │   │   └── test-mod
    │   │       └── run.sh
    │   ├── subsubdir2
    │   │   ├── run.sh
    │   │   └── test-mod
    │   │       └── run.sh
    │   └── subsubdir3
    │       ├── run.sh
    │       └── test-mod
    │           └── run.sh
    └── subdir2
        ├── subsubdir1
        │   ├── run.sh
        │   └── test-mod
        │       └── run.sh
        ├── subsubdir2
        │   ├── run.sh
        │   └── test-mod
        │       └── run.sh
        └── subsubdir3
            ├── run.sh
            └── test-mod
                └── run.sh
---
and its associated input:
---
Tree:
  First directory level:   <-- arbitrary name (shown during selection)
    - dir1                 <-- directories must be preceded by dashes
    - dir2
  Second directory level:
    - subdir1              <-- each dir above contains all these
    - subdir2
  Third directory level:
    - subsubdir1           <-- each dir above contains all these
    - subsubdir2
    - subsubdir2

Modes:
  Mode 1:                  <-- name of mode (shown during selection)
    cmd: ./run.sh          <-- command to be run ('command: ' is equally valid)
  Mode 2: 
    cmd: ./run.sh
    dir: test-{mod}        <-- subdir under subsubdir* where {mod} is replaced
---                            by whatever follows the --modifier (or -m) flag
"""

epilog = """Run:
> trn --example
to see an example tree structure with its associated input file.
"""


# 80-23=57 spaces wide

version_help = f'\
treerun ver. {version("treerun")}'

modifier_help = """modifiers are used to substitute {mod} in 
the \'Modes\' block of the input YAML-file
"""

input_help = """input file (YAML-format) that contains a \'Tree\'-block
with the names of all directories in each level and a
\'Modes\'-block that contains all commands
"""

exclude_help = """the program will exclude all nodes corresponding to any 
dir-name given here
"""

all_help = """automatically selects all non-excluded paths without any
prompts
"""

log_help = """information about which programs were run and which 
were not will be stored in a log file with the name
given here
"""

example_help = """prints a possible tree structure and the contents of an
associated input file
"""

parser = argparse.ArgumentParser(
    prog='trn',
    description=description,
    epilog=epilog,
    formatter_class=argparse.RawTextHelpFormatter,
)
parser.add_argument(
    '--version', action='version',
    version=version_help,
)
parser.add_argument(
    '-m', '--modifier', type=str, 
    help=modifier_help,
)
parser.add_argument(
    '-i', '--input', default='input.yaml',
    help=input_help,
)
parser.add_argument(
    '-e', '--exclude', nargs='+', default=[],
    help=exclude_help,
)
parser.add_argument(
    '-a', '--all', action='store_true',
    help=all_help,
)
parser.add_argument(
    '-o', '--output', default=None,
    help=log_help,
)
parser.add_argument(
    '--example', action='store_true',
    help=example_help,
)

args = parser.parse_args()


class ExitCode:
    """Legend:
      0:  could not locate the necessary files
      1:  use input caused program to close
    """
    def __init__(self, exit_code=None,loc=''):
        self.exit_code = exit_code
        self.legend = {
            0:'A problem occurred during input-selection',
            1:'Missing YAML-input',
            2:'The necessary files could not be found',
            3:'Error converting placeholders',
            4:'Missing mode-command',
            5:'Log-file does not exist',
        }
        if self.exit_code != None:
            print(f'exit code: {self.exit_code}')
            #quit()
            sys.exit()

        #with open(args.output, 'a') as sys.stdout:
        #    print(f'code: {code}')

    def interpret(self, exit_code):
        return interpretations[exit_code]


def whitespace(strings, tab_width=4, max_length=None):
    """Returns a dictionary with the same keys as the original dictionary but
    with a number of spaces as values instead.

    The number of spaces corresponds to the difference between all keys and the
    longest key (+tab_width).
    """
    if type(strings) == list:
        lengths = [len(string) for s in strings]
        if max_length == None:
            longest_string = max(lengths)
        else:
            longest_string = max_length+tab_width
        spaces = {string:(longest_string-length) for string, length in zip(strings, lengths)}

    elif type(strings) == dict:
        # Get longest name
        name_lengths = {key:len(key) for key in strings}
        if max_length == None:
            longest_string = name_lengths[max(name_lengths, key=name_lengths.get)]+tab_width
        else:
            longest_string = max_length+tab_width

        # Create whitespace map
        spaces = {key:(longest_string-val)*' ' for key,val in name_lengths.items()}

    return spaces, longest_string


def tabulate(data, tab_width=None):
    """Tabulates keys and values of a given dictionary into two columns
    """
    assert type(data)==dict, ValueError('The \'tabulate\' function takes a dictionary as input.')
    space, _ = whitespace(data, max_length=tab_width)
    for key,val in data.items():
        print(f'{key}{space[key]}{val}')


def convert_placeholders(dictionary, args):
    """Returns a copy of the dictionary where placeholders have been replaced
    by the variables defined in 'args'.

    Placeholders in the YAML-file are defined as {arg} where 'arg' will be 
    replaced by its corresponding mapping defined by 'args'

    Keyword arguments:
      dictionary:  dictionary subject to placeholder conversion
      args:        dictionary with proper placeholder-variable map, e.g,
                   args = dict(mod=modifier, mode=mode, ...)
    """
    tmp = copy.deepcopy(dictionary)

    # Attempt conversion based on type
    for key,val in dictionary.items():
        if type(val) == list:
            for i,v in enumerate(val):
                # Convert if subelement is string
                if type(v) == str:
                    tmp[key][i] = v.format(**args)

        elif type(val) == dict:
            for k,v in val.items():
                # Convert if subelement is string
                if type(v) == str:
                    tmp[key][k] = v.format(**args)

        # Convert if subelement is string
        elif type(val) == str:
            tmp[key] = val.format(**args)

    return tmp


def make_selection(description, options, select_all):
    if select_all:
        selection = [opt for opt in options if opt not in args.exclude]
    else:            
        while True:
            # Attempt selection
            try:
                index_selection = input(description)
            except EOFError as e:
                print(e)
                ExitCode(0)

            # Evaluate selection, repeat attempt if criteria not met
            ## Single entry selections are simple index-slices of a list
            if index_selection.isdigit():
                index_selection = int(index_selection)

                ## Make sure index is valid
                if 1 <= index_selection < len(options)+1:
                    if type(options) == list:
                        # Shift of -1 needed for list since prompt starts from 1
                        selection = options[index_selection-1]
                    
                    # Do not quite understand why this is needed
                    elif type(options) == dict:
                        selection = options[index_selection]

                    # Keep only non-excluded selections
                    if selection not in args.exclude:
                        break
                    else:
                        print('This option has been excluded. Please select another.')
                else:
                    print(f'Integer selections must be between 1 and {len(options)}')
                continue

            # If selection is not digit, select all using '*' or simply 'enter'
            elif (index_selection in ['', '*']) and (type(options) != dict):
                # Filter all excluded if multiple selections
                selection = [s for s in options if s not in args.exclude]
                break
            elif type(options) == dict:
                print(f'Only one mode at a time can be selected.')
            else:
                print(f'Enter an integer or press enter to select all.')
            continue

    return selection


def level_select(dictionary, exclude):
    choices = {}
    integer_to_mode_map = {}
    for key,val in dictionary.items():
        # Show options available for selection
        header(key)
        if type(val) == list:
            for i, v in enumerate(val):
                if v in exclude:
                    print(f'({i+1}) {v} (will be excluded)')
                else:
                    print(f'({i+1}) {v}')

            # Make selection
            selection = make_selection('Enter an integer to select an option (press enter to select all): ', val, select_all=args.all)

            # Selection must be a list (preparation for cartiesian product)
            if type(selection) == str:
                choices[key] = [selection]
            else:
                choices[key] = selection

    return choices


def header(string, width=80):
    """Simple header with lines abive and below (em-dash: U+2014).
    """
    print(width*'\u2014')
    print(string)
    print(width*'\u2014')


def mode_select(dictionary, modifier):
    integer_to_mode_map = {}

    # Select mode
    header('Select mode:')
    for i, (key,val) in enumerate(dictionary.items()):
        print(f'({i+1}) {key}')
        integer_to_mode_map[i+1] = key,val
    selection = make_selection('Select an option: ', integer_to_mode_map, select_all=False)

    return selection


def get_paths(dictionary):
    """Returns a list of paths genereted from Cartesian products of the values
    in a given dictionary.

    Keyword arguments:
      dictionary: non-nested dictionary will values being of type 'list'
    """
    prod = itertools.product(*dictionary.values())
    paths = list(map(lambda e: '/'+'/'.join(e), prod))
    return paths


def check_files(paths):
    """Given a list of paths, returns the lists of the paths that does, and
    does not, exist on the drive.

    Keyword argument:
      paths:  list of paths
    """
    cwd = os.getcwd()

    # Determine which directories does and does not exist
    is_dir = lambda p: os.path.isdir(p)
    found, not_found = [], []
    for path in paths:
        if is_dir(cwd+path):
            found.append(path)
        else:
            not_found.append(path)

    # Make sure user wants to continue if missing files
    header(f'Checking directories:')

    ## None of the directories were found: exit
    if len(found) == 0:
        print('Could not locate the relevant directories.')
        print('\nPlease make sure that the appropriate directories exist and that all modifiers\nin the YAML input (if any) have been supplied.')
        ExitCode(2)

    ## Some directories were not found, still continue?
    elif len(not_found) > 0:
        print('Unable to locate the following directories:')
        for file in not_found:
            print(file)

        #if input('Do you still want to continue (y/[n])? ').lower() not in ['y', 'yes']:
        #    print('Closing.')
        try:
            q = input('Do you still want to continue (y/[n])? ').lower()
            if q not in ['y', 'yes']:
                print('Closing.')
        except:
            ExitCode(0)

    # All directories were found
    elif (len(found) == len(paths)) and (len(not_found) == 0):
        print('All relevant directories exist.')
        print('\nProceeding with submission attempt.')

    return found, not_found



def graft_paths(paths:list, graft_point:str) -> list:
    """Given a list of paths, returns a list of paths pruned and grafted with
    a new path specified as a mode dir in the input.

    Keyword arguments:
      paths:        list of paths to be pruned, if possible
      graft_point:  point of entry for grafting where the string section before
                    the first '/' is part of one of the given paths
    """
    pruned_paths = []
    
    entry_point = graft_point[1:].split('/')[0]
    for path in paths:
        if (len(graft_point) > 0) and (entry_point in path):
            pruned_path = path.partition(entry_point)[0]+graft_point[1:]
            if pruned_path not in pruned_paths:
                pruned_paths.append(pruned_path)
    
    return pruned_paths




#def run(mode, selected_levels, modifier, log_file):
def run(data:dict, modifier, log_file):
    #levels = data['Tree']
    #modes = data['Modes']

    # Select levels and modes
    selected_levels = level_select(data['Tree'], args.exclude)
    mode, mode_dict = mode_select(data['Modes'], args.modifier)

    #mode, mode_dict = mode
    successful, unsuccessful = [],[]
    cwd = os.getcwd()
    
    # Convert placeholders to variables
    ## Defined in input.yaml
    if 'Handles' in data.keys():
        placeholder_map = data['Handles']
    elif 'Placeholders' in data.keys():
        placeholder_map = data['Placeholders']
    else:
        ## Default is not in yaml
        placeholder_map = dict(
            mod=modifier,
            mode=mode,
        )

    # Make sure that cli input overrides anything in config
    if (modifier is not None) or (modifier != ''):
        placeholder_map['mod'] = modifier
    
    # Attempt conversion
    try:
        mode_dict = convert_placeholders(mode_dict, placeholder_map)    
    except:
        ExitCode(3)

    # Summarise and print selections.
    ## Merge special variables with choices, conditional or non-conditional
    ## Tabulate merged dict
    header('Summary:')
    tmp = {
        'Mode:':mode,
    }
    if (modifier is not None) or (modifier != ''):
        tmp['Modifier:'] = modifier
    tabulate(tmp|selected_levels)

    # Get args if given as list in yaml
    try:
        cmd_args = ' '+' '.join(mode_dict['args'])
    except:
        try:
            cmd_args = ' '+' '.join(mode_dict['arguments'])
        except:
            cmd_args = ''

    # Get command
    try:
        cmd = mode_dict['cmd']+cmd_args
    except:
        try:
            cmd = mode_dict['command']+cmd_args
        except:
            ExitCode(4)
            raise KeyError('The current mode does not seem to have any associated command.')

    # Get sub-dir to run in, if speecified
    try:
        run_dir = '/'+mode_dict['dir']
    except:
        try:
            run_dir = '/'+mode_dict['directory']
        except:
            run_dir = ''

    # Attempts pruning of paths if the specified run_dir has a lower level than 
    # the maximum
    paths = get_paths(selected_levels)
    pruned_paths = graft_paths(paths, run_dir)

    # Get paths and make find out which actually exist
    if len(pruned_paths) == 0:
        paths = [p+run_dir for p in paths]
        found, not_found = check_files(paths)
    else:
        paths = [p for p in pruned_paths]
        found, not_found = check_files(pruned_paths)

    # Attempt to submit all files that were found
    header(f'Submitting:')
    for path in found:
        # Attempt to run
        if cwd[-1] == '/':
            cwd = cwd[:-1]

        try:
            os.chdir(cwd+path)
            tabulate(
                {
                    'Moving to:':path,
                    'Running:':cmd,
                }
            )
            subprocess.call(cmd, shell=True)
            successful.append(path)

        # Log unsuccessful attempts
        except FileNotFoundError as e:
            print(e)
            print('Proceding to next file.')
            unsuccessful.append(path)

    # Lengths of all paths, used for even tabulating
    max_length = max([len(string) for string in found+not_found+unsuccessful])

    # Logging
    if log_file != None:
        try:
            with open(f'{cwd}/{log_file}', 'a') as sys.stdout:
                print(80*'\u2014')
                tabulate(
                    {
                        'Mode:':mode,
                        'Submitted:':datetime.datetime.now(),
                        'Root dir:':cwd,
                    }
                )
                print()
                print('Successfully submitted:')
                tabulate({p:cmd for p in successful}, max_length)

                if len(unsuccessful) > 0:
                    print()
                    print('Unsuccessful submissions:')
                    tabulate({p:cmd for p in unsuccessful}, max_length)

                if len(not_found) > 0:
                    print()
                    print('Not found:')
                    tabulate({p:cmd for p in not_found}, max_length)
        except:
            ExitCode(5)


#if __name__ == '__main__':
def main():
    if args.example:
        print(example_tree)
        quit()
    
    if args.exclude != []:
        print(f'Ignoring: {args.exclude}')

    # Current working dir
    cwd = os.getcwd()

    # Obtain levels and modes
    input_path = f'{cwd}/{args.input}'
    if os.path.isfile(input_path):
        with open(input_path, 'r') as f:
            data = yaml.safe_load(f)
        #levels = data['Tree']
        #modes = data['Modes']
    else:
        ExitCode(1)
        raise FileNotFoundError('Please make sure there is a proper input file (YAML) in the root directory.')

    # Select levels
    #choices = level_select(levels, args.exclude)

    # Select modes and run
    #mode = mode_select(modes, args.modifier)
    #quit()
    #run(mode, choices, args.modifier, log_file=args.output)
    run(data, args.modifier, log_file=args.output)


if __name__ == '__main__':
    main()
