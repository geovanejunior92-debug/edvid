#!/bin/bash
cd /home/user/edvid/narracao_noia
i=0
while IFS= read -r line; do
  i=$((i+1)); n=$(printf %02d $i)
  [ -s partes/$n.wav ] && continue
  code=$(curl -s -X POST http://localhost:3900/generate --form-string "text=$line" -F profile_id=2ae98cae -F engine=voxcpm2 -F language=Portuguese -F seed=1322101234 -o partes/$n.wav -w "%{http_code}")
  echo "parte $n: $code"
done < roteiro.txt
echo FIM
