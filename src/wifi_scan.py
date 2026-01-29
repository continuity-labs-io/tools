import CoreWLAN
import sys

def scan_networks():
    # Access the default Wi-Fi interface
    interface = CoreWLAN.CWWiFiClient.sharedWiFiClient().interface()
    
    # Scan for networks (None, None scans for everything)
    try:
        networks, error = interface.scanForNetworksWithName_error_(None, None)
    except Exception as e:
        print(f"Error executing scan: {e}")
        return

    if error:
        print(f"Error scanning: {error}")
        return

    # Header
    print(f"\n{'SSID':<30} {'RSSI (dBm)':<12} {'NOISE (dBm)':<12}")
    print("=" * 56)
    
    # Sort by Signal Strength (RSSI), strongest first
    # Using a set to deduplicate SSIDs if multiple BSSIDs broadcast the same name
    seen_ssids = set()
    unique_networks = []
    
    missing_ssid_count = 0

    for network in networks:
        ssid = network.ssid()
        if ssid:
            if ssid not in seen_ssids:
                unique_networks.append(network)
                seen_ssids.add(ssid)
        else:
            # Handle hidden or permission-blocked networks
            missing_ssid_count += 1
            # We can't deduplicate easily without SSID/BSSID, but let's just add them if we want to show them
            # For now, let's skip them in the main list but track count
            pass
            
    sorted_networks = sorted(unique_networks, key=lambda n: n.rssiValue(), reverse=True)
    
    if not sorted_networks and missing_ssid_count > 0:
        print("\nWARNING: Found networks but could not read SSIDs.")
        print("This usually happens because the terminal or python executable")
        print("does not have 'Location Services' permission.")
        print("Please go to System Settings > Privacy & Security > Location Services")
        print("and ensure your terminal application is checked.\n")

    for network in sorted_networks:
        print(f"{network.ssid():<30} {network.rssiValue():<12} {network.noiseMeasurement():<12}")
    print("\n")

if __name__ == "__main__":
    scan_networks()
