# Capture the emulated replay of one scheme with TShark and export a CSV.
# Run from project root:
#   powershell -ExecutionPolicy Bypass -File .\packet_capture\run_emulated_capture.ps1 -Scheme llq_only -Steps 30
param(
    [string]$Scheme = "llq_only",
    [int]$Steps = 30,
    [string]$Interface = "\Device\NPF_Loopback"
)

$tshark = "C:\Program Files\Wireshark\tshark.exe"
if (-not (Test-Path $tshark)) { Write-Error "TShark not found."; exit 1 }

$pcap = "results\capture_$Scheme.pcapng"
$csv  = "results\capture_$Scheme.csv"

$cap = Start-Process -FilePath $tshark -PassThru -NoNewWindow -ArgumentList `
    "-i", "`"$Interface`"", "-f", "`"udp portrange 50001-50010`"", "-w", $pcap
Start-Sleep -Seconds 3

python packet_capture\emulated_replay.py --scheme $Scheme --steps $Steps

Start-Sleep -Seconds 2
Stop-Process -Id $cap.Id -Force
Start-Sleep -Seconds 1

& $tshark -r $pcap -Y "udp" -T fields -E "header=y" -E "separator=," `
    -e frame.number -e frame.time_epoch -e ip.dsfield.dscp -e udp.dstport -e udp.payload `
    | Out-File -Encoding ascii $csv

Write-Host "Saved $pcap and $csv"
