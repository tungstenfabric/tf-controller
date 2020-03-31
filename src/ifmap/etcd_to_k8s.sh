#!/bin/bash -e
#
# Author:  Edwin P. Jacques (ejacques@juniper.net)
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#

if [[ "$*" =~ -(help|\?|h)( |$) ]] || [[ -z "$1" ]]; then
cat <<-EOF

Purpose: Filter to generate Kubernetes JSON data from ETCD JSON data.
         Each file is processed one by one.  Original file is saved 
         with "SAVED_" pre-pended.

Example conversion of bulk data: 
  ./etcd_to_k8s.sh client/testdata/bulk_sync_k8s.json

Example conversion of watch data:
  ./etcd_to_k8s.sh testdata/k8s_vmi_list_map_prop_p1.json 

EOF
exit 0
fi

die() {
  echo "$*" >&2
  exit 1
}

libdir="$(readlink -f "$(dirname "$0")")"
# change value to "bulk" to convert bulk data
function=watch

for file in "$@"; do
  [[ -r "$file" ]] || die "File not found: \"$file\""

  if [[ $file =~ bulk ]]; then
    function=bulk
  fi

  saved_file="$(dirname "$file")/SAVED_$(basename "$file")"
  if [[ -r "$saved_file" ]]; then
    if [[ -n "$retry" ]]; then
      echo "$saved_file already exists, RETRYING..." >&2
    else
      echo "$saved_file already exists, SKIPPING..." >&2
      continue
    fi
  else
    echo "Backing up ${file} to ${saved_file}..." >&2
    cp "$file" "$saved_file" || die "Copy failed."
  fi

  if [[ "$function" == 'watch' ]]; then
     if [[ ! -r "${saved_file}.bak" ]]; then
       echo "Fixing incorrect JSON syntax and saving to ${saved_file}.bak" >&2
       cp "$saved_file" "${saved_file}.bak"
       sed -r -e 's;^\{;[;' -e 's;^\};];' -e  's;("/(CREATE|UPDATE|DELETE|PAUSED)[/a-z0-9_\-]*"): *\{;\{ \"event\": \1,;' -e 's;"/PAUSED/*",;"/PAUSED/";' "${saved_file}.bak" | jq '.' > "$saved_file"
     fi
  fi

  echo "Converting $function etcd data to k8s in ${file}..." >&2
  jq -L "$libdir" "import \"etcd_to_k8s\" as lib; lib::${function}_etcd_to_k8s" "$saved_file" >"$file" || die "Conversion failed."
done
