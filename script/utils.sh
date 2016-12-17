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

# Resolves project version based on v* tags in git repository. If HEAD is not
# tagged (i.e. this is not a release), then it returns last version with
# suffix -dev.
repo_version() {
	local desc

	# If git HEAD is tagged as v*, then it prints name of the tag.
	if desc="$(git describe --tags --exact-match --match 'v*' 2>/dev/null)"; then
		echo "${desc#v}"
	# Prints name of the last v* tag in the tree with suffix `-<n>-<abbrev>`.
	elif desc="$(git describe --tags --match 'v*' 2>/dev/null)"; then
		echo "$desc" | sed -En 's/^v([^-]+).*/\1-dev/p'
	else
		return 1
	fi
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
