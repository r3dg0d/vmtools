_iosvm() { COMPREPLY=($(compgen -W "doctor import imports fetch create list start launch stop status info console display gui sim delete config help" -- "${COMP_WORDS[1]}")); }
complete -F _iosvm iosvm
