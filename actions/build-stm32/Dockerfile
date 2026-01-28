# Container image that runs your code
FROM xanderhendriks/stm32cubeide:15.0

# Tools your script needs
RUN apt-get -y update && \
    apt-get -y install curl python3 python3-pycryptodome python3-ecdsa python3-pyelftools python3-numpy git srecord ca-certificates bear cppcheck jq \
    && ln -s $(which python3) /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# If your entrypoint uses bash, uncomment this line:
# RUN apt-get update && apt-get install -y --no-install-recommends bash && rm -rf /var/lib/apt/lists/*

# Copy and normalize the entrypoint
COPY entrypoint.sh /entrypoint.sh

# Strip CRLF if the file was committed with Windows line endings,
# remove a possible UTF-8 BOM, and make it executable & world-readable.
RUN awk 'NR==1{sub(/^\xEF\xBB\xBF/,"")}{gsub(/\r$/,"")}1' /entrypoint.sh > /entrypoint.fixed && \
    cat /entrypoint.fixed > /entrypoint.sh && rm /entrypoint.fixed && \
    chmod 0755 /entrypoint.sh && \
    chown root:root /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
