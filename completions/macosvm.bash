_macosvm() { COMPREPLY=($(compgen -W "doctor import imports extract fetch-recovery create list start launch stop shutdown status info display gui console delete config help" -- "${COMP_WORDS[1]}")); }
complete -F _macosvm macosvm
