# NETPULSE: capture real UDP replay traffic with TShark (native Windows).
# Prerequisites: Wireshark (with TShark + Npcap, tick "Support loopback traffic").
# Run from the project root:  .\packet_capture\run_capture.ps1 -Steps 30
param(
    [int]$Steps = 30,
    [string]$Interface = "\Device\NPF_Loopback"
)

$tshark = "C:\Program Files\Wireshark\tshark.exe"
if (-not (Test-Path $tshark)) { Write-Error "TShark not found. Install Wireshark first."; exit 1 }

$pcap = "results\netpulse_capture.pcapng"
$csv  = "results\wireshark_udp.csv"

Write-Host "Starting capture on '$Interface'..."
$cap = Start-Process -FilePath $tshark -PassThru -NoNewWindow -ArgumentList `
    "-i", "`"$Interface`"", "-f", "`"udp portrange 50001-50010`"", "-w", $pcap
Start-Sleep -Seconds 3

python packet_capture\udp_replay.py --steps $Steps

Start-Sleep -Seconds 2
Stop-Process -Id $cap.Id -Force
Start-Sleep -Seconds 1

& $tshark -r $pcap -Y "udp" -T fields -E "header=y" -E "separator=," `
    -e frame.number -e frame.time_epoch -e frame.len -e udp.srcport -e udp.dstport -e udp.length `
    | Out-File -Encoding ascii $csv

Write-Host "Saved $pcap and $csv"
