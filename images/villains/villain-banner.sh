# ABOUTME: The Joker's shell banner (#714), laid in both Jokers at /etc/villain-banner.sh, which ENV names. busybox sh
# ABOUTME: runs ENV's file only for an interactive shell: `kubectl exec -it <pod> -- sh` greets, a plain exec does not.
# Harmless by design: printf lines only. No network, no file writes, and nothing that ends the shell it runs in.
printf '\033[32m'
printf '%s\n' '01001010 01001111 01001011 01000101 01010010   uplink to maintenance-shell ............ OK'
printf '%s\n' '>> image signature ......... none   >> registry vetted ......... nope   >> admission ......... waved through'
printf '%s\n' '>> elevating privileges .... 4%  12%  57%  98%  just kidding, I only print text'
printf '\033[0m'
printf '%s\n' 'ACCESS GRANTED... just kidding, you deployed me. Why so trusting about admission control?'
printf '%s\n' 'HAHAHA! The Joker'
