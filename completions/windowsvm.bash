_windowsvm() { COMPREPLY=($(compgen -W "list create launch start stop shutdown reboot pause resume delete info console gui snapshot snapshots restore clone iso network doctor config help" -- "${COMP_WORDS[1]}")); }
complete -F _windowsvm windowsvm
