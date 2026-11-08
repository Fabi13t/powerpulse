#include <iostream>
#include <winsock2.h>
#include <windows.h>
#include <setupapi.h>
#include <batclass.h>
#include <string>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "setupapi.lib")

// GUID de la clase de dispositivos "Bateria" (GUID_DEVCLASS_BATTERY)
static const GUID GUID_BATERIA =
    {0x72631e54, 0x78a4, 0x11d0, {0xbc, 0xf7, 0x00, 0xaa, 0x00, 0xb7, 0xb3, 0x2a}};

// Datos de salud y consumo que entrega el driver ACPI de la bateria
struct InfoBateria {
    long voltajeMv = -1;      // voltaje en milivoltios
    long consumoMw = -1;      // potencia en milivatios (positivo = descargando)
    long capDisenoMwh = -1;   // capacidad de fabrica
    long capActualMwh = -1;   // capacidad maxima actual (con desgaste)
    long ciclos = -1;         // ciclos de carga
};

// Consulta la bateria directamente al driver ACPI mediante IOCTL
InfoBateria LeerInfoBateria() {
    InfoBateria r;
    HDEVINFO hdev = SetupDiGetClassDevsA(&GUID_BATERIA, NULL, NULL,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (hdev == INVALID_HANDLE_VALUE) return r;

    SP_DEVICE_INTERFACE_DATA did{};
    did.cbSize = sizeof(did);
    if (SetupDiEnumDeviceInterfaces(hdev, NULL, &GUID_BATERIA, 0, &did)) {
        DWORD requerido = 0;
        SetupDiGetDeviceInterfaceDetailA(hdev, &did, NULL, 0, &requerido, NULL);
        PSP_DEVICE_INTERFACE_DETAIL_DATA_A detalle =
            (PSP_DEVICE_INTERFACE_DETAIL_DATA_A)LocalAlloc(LPTR, requerido);

        if (detalle) {
            detalle->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_A);
            if (SetupDiGetDeviceInterfaceDetailA(hdev, &did, detalle, requerido, &requerido, NULL)) {
                HANDLE hBat = CreateFileA(detalle->DevicePath, GENERIC_READ | GENERIC_WRITE,
                                          FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                                          OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
                if (hBat != INVALID_HANDLE_VALUE) {
                    BATTERY_QUERY_INFORMATION bqi{};
                    DWORD espera = 0, bytes = 0;

                    if (DeviceIoControl(hBat, IOCTL_BATTERY_QUERY_TAG, &espera, sizeof(espera),
                                        &bqi.BatteryTag, sizeof(bqi.BatteryTag), &bytes, NULL)
                        && bqi.BatteryTag != 0) {

                        // Capacidad de diseno, capacidad actual y ciclos
                        BATTERY_INFORMATION bi{};
                        bqi.InformationLevel = BatteryInformation;
                        if (DeviceIoControl(hBat, IOCTL_BATTERY_QUERY_INFORMATION, &bqi, sizeof(bqi),
                                            &bi, sizeof(bi), &bytes, NULL)
                            && !(bi.Capabilities & BATTERY_CAPACITY_RELATIVE)) {
                            r.capDisenoMwh = (long)bi.DesignedCapacity;
                            r.capActualMwh = (long)bi.FullChargedCapacity;
                            if (bi.CycleCount > 0) r.ciclos = (long)bi.CycleCount;
                        }

                        // Voltaje y potencia actual
                        BATTERY_WAIT_STATUS bws{};
                        bws.BatteryTag = bqi.BatteryTag;
                        BATTERY_STATUS bs{};
                        if (DeviceIoControl(hBat, IOCTL_BATTERY_QUERY_STATUS, &bws, sizeof(bws),
                                            &bs, sizeof(bs), &bytes, NULL)) {
                            if (bs.Voltage != BATTERY_UNKNOWN_VOLTAGE) r.voltajeMv = (long)bs.Voltage;
                            if ((ULONG)bs.Rate != BATTERY_UNKNOWN_RATE) r.consumoMw = -bs.Rate; // el driver da negativo al descargar
                        }
                    }
                    CloseHandle(hBat);
                }
            }
            LocalFree(detalle);
        }
    }
    SetupDiDestroyDeviceInfoList(hdev);
    return r;
}

// Calcula el % de uso de CPU comparando dos lecturas de GetSystemTimes
int ObtenerUsoCPU() {
    FILETIME idleTime, kernelTime, userTime;
    if (!GetSystemTimes(&idleTime, &kernelTime, &userTime)) return 0;

    static ULONGLONG prevIdle = 0, prevKernel = 0, prevUser = 0;

    ULONGLONG idle = ((ULONGLONG)idleTime.dwHighDateTime << 32) | idleTime.dwLowDateTime;
    ULONGLONG kernel = ((ULONGLONG)kernelTime.dwHighDateTime << 32) | kernelTime.dwLowDateTime;
    ULONGLONG user = ((ULONGLONG)userTime.dwHighDateTime << 32) | userTime.dwLowDateTime;

    ULONGLONG usrDiff = user - prevUser;
    ULONGLONG kerDiff = kernel - prevKernel;
    ULONGLONG idlDiff = idle - prevIdle;

    prevIdle = idle;
    prevKernel = kernel;
    prevUser = user;

    ULONGLONG total = usrDiff + kerDiff;
    if (total == 0) return 0;

    return (int)((total - idlDiff) * 100 / total);
}

int main() {
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        std::cout << "Error al iniciar Winsock\n";
        return 1;
    }

    SOCKET sendSocket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);

    sockaddr_in recvAddr{};
    recvAddr.sin_family = AF_INET;
    recvAddr.sin_port = htons(5005);
    recvAddr.sin_addr.s_addr = inet_addr("127.0.0.1");

    SYSTEM_POWER_STATUS sps;

    std::cout << "=== PowerPulse: Recolector C++ Activo ===\n";
    ObtenerUsoCPU();

    while (true) {
        // RF-001 + validacion: 255 significa "desconocido"
        if (GetSystemPowerStatus(&sps) && sps.BatteryLifePercent <= 100) {
            int porcentajeBat = sps.BatteryLifePercent;
            int cargando = (sps.ACLineStatus == 1) ? 1 : 0;
            long tiempoRestante = (sps.BatteryLifeTime == (DWORD)-1)
                                      ? -1 : (long)sps.BatteryLifeTime;
            int usoCpu = ObtenerUsoCPU();
            InfoBateria info = LeerInfoBateria();

            // RF-005: mensaje en formato JSON (-1 = dato no disponible)
            std::string mensaje =
                "{\"bateria\":" + std::to_string(porcentajeBat) +
                ",\"cargando\":" + std::to_string(cargando) +
                ",\"tiempo_restante_seg\":" + std::to_string(tiempoRestante) +
                ",\"uso_cpu\":" + std::to_string(usoCpu) +
                ",\"voltaje_mv\":" + std::to_string(info.voltajeMv) +
                ",\"consumo_mw\":" + std::to_string(info.consumoMw) +
                ",\"cap_diseno_mwh\":" + std::to_string(info.capDisenoMwh) +
                ",\"cap_actual_mwh\":" + std::to_string(info.capActualMwh) +
                ",\"ciclos\":" + std::to_string(info.ciclos) + "}";

            // RF-006: envio por UDP
            sendto(sendSocket, mensaje.c_str(), (int)mensaje.length(), 0,
                   (SOCKADDR*)&recvAddr, sizeof(recvAddr));

            std::cout << "[PowerPulse C++] Bat: " << porcentajeBat << "% | Cargando: " << cargando
                      << " | CPU: " << usoCpu << "% | " << info.voltajeMv << " mV | "
                      << info.consumoMw << " mW | Ciclos: " << info.ciclos << std::endl;
        } else {
            std::cout << "[PowerPulse C++] Lectura de energia no valida, se reintenta\n";
        }

        Sleep(2000);
    }

    closesocket(sendSocket);
    WSACleanup();
    return 0;
}
