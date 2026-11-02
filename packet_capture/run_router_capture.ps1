# Capture the 50-node emulated router network (one loopback IP per node) with TShark.
#   powershell -ExecutionPolicy Bypass -File .\packet_capture\run_router_capture.ps1 -Scheme llq_only -Steps 30
param(
    [string]$Scheme = "llq_only",
    [int]$Steps = 30,
    [string]$Interface = "\Device\NPF_Loopback"
)

$tshark = "C:\Program Files\Wireshark\tshark.exe"
if (-not (Test-Path $tshark)) { Write-Error "TShark not found."; exit 1 }

$pcap = "results\router_$Scheme.pcapng"
$csv  = "results\router_$Scheme.csv"

$cap = Start-Process -FilePath $tshark -PassThru -NoNewWindow -ArgumentList `
    "-i", "`"$Interface`"", "-f", "`"udp port 40000`"", "-w", $pcap
Start-Sleep -Seconds 3

python packet_capture\router_network.py --scheme $Scheme --steps $Steps

Start-Sleep -Seconds 2
Stop-Process -Id $cap.Id -Force
Start-Sleep -Seconds 1

& $tshark -r $pcap -Y "udp" -T fields -E "header=y" -E "separator=," `
    -e frame.number -e frame.time_epoch -e ip.src -e ip.dst -e ip.dsfield.dscp -e udp.payload `
    | Out-File -Encoding ascii $csv

Write-Host "Saved $pcap and $csv"
