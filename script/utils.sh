# vim: set ts=4:

: ${BASE_DIR:="$(pwd)"}
: ${BUILD_DIR:="$(pwd)/build"}
: ${TARGET_DIR:="$(pwd)/dist"}


die() {
	# bold red
	printf '\033[1;31mERROR:\033[0m %s\n' "$1" >&2
	shift
	printf '  %s\n' "$@"
	exit 2
}

einfo() {
	# bold cyan
	printf '\033[1;36m> %s\033[0m\n' "$@" >&2
}

ewarn() {
	# bold yellow
	printf '\033[1;33m> %s\033[0m\n' "$@" >&2
}

has() {
	command -v "$1" >/dev/null 2>&1
}

sed_inplace() {
	if sed --version >/dev/null 2>&1; then
		sed -r -i'' "$@"  # GNU or Busybox sed
	else
		sed -E -i '' "$@"  # BSD sed
	fi
}
