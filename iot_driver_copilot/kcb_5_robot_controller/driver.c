/*
 * KCB-5 Robot Controller HTTP Driver
 * Implements HTTP server exposing robot controller I/O/servo/analog endpoints.
 * All configuration is via environment variables:
 *   KCB5_DEVICE_PORT     - UART device path (e.g. /dev/ttyS1)
 *   KCB5_UART_BAUDRATE   - UART baudrate (e.g. 115200)
 *   HTTP_HOST            - HTTP server host (default: 0.0.0.0)
 *   HTTP_PORT            - HTTP server port (default: 8080)
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <termios.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <signal.h>

#define MAX_REQ_SIZE 4096
#define MAX_RESP_SIZE 8192
#define MAX_JSON_SIZE 512
#define MAX_SERVO_COUNT 8
#define MAX_DIO_COUNT 16
#define MAX_AD_COUNT 4

// UART Communication
static int uart_fd = -1;

// Signal handler for clean exit
volatile sig_atomic_t keep_running = 1;
void int_handler(int _) { keep_running = 0; }

// Utility: Read environment variable with default
const char* envd(const char *name, const char *def) {
    const char *v = getenv(name);
    return v && *v ? v : def;
}

// UART: open and configure
int uart_open(const char *port, int baudrate) {
    int fd = open(port, O_RDWR | O_NOCTTY | O_SYNC);
    if (fd < 0) return -1;
    struct termios tty;
    memset(&tty, 0, sizeof tty);
    if(tcgetattr(fd, &tty) != 0) { close(fd); return -1; }
    cfsetospeed(&tty, baudrate);
    cfsetispeed(&tty, baudrate);
    tty.c_cflag = (tty.c_cflag & ~CSIZE) | CS8;
    tty.c_iflag &= ~IGNBRK;
    tty.c_lflag = 0;
    tty.c_oflag = 0;
    tty.c_cc[VMIN]  = 0;
    tty.c_cc[VTIME] = 20; // 2s timeout
    tty.c_cflag |= (CLOCAL | CREAD);
    tty.c_cflag &= ~(PARENB | PARODD | CSTOPB | CRTSCTS);
    if(tcsetattr(fd, TCSANOW, &tty) != 0) { close(fd); return -1; }
    return fd;
}

// UART: Send command and receive response
int uart_cmd(const char *cmd, char *resp, size_t resp_len) {
    // Write command (add \n)
    char buf[128];
    snprintf(buf, sizeof(buf), "%s\n", cmd);
    if(write(uart_fd, buf, strlen(buf)) < 0) return -1;
    // Read response (until \n or timeout)
    size_t n = 0;
    while(n < resp_len-1) {
        char c;
        int r = read(uart_fd, &c, 1);
        if(r <= 0) break;
        if(c == '\n') break;
        resp[n++] = c;
    }
    resp[n] = 0;
    return n;
}

// Minimal HTTP utilities

int starts_with(const char *s, const char *prefix) {
    return strncmp(s, prefix, strlen(prefix)) == 0;
}

void http_response(int client, int code, const char *ctype, const char *body) {
    char buf[MAX_RESP_SIZE];
    snprintf(buf, sizeof(buf),
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: %s\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n\r\n"
        "%s",
        code, code==200?"OK":(code==400?"Bad Request":"Internal Error"),
        ctype, strlen(body), body);
    write(client, buf, strlen(buf));
}

void http_notfound(int client) {
    http_response(client, 404, "text/plain", "Not found");
}

// DIO API

int dio_read(int *values, int *count) {
    char resp[128];
    if(uart_cmd("pio_read", resp, sizeof(resp)) < 0) return -1;
    // Example response: "PIO:0F0A" (hex bitmap)
    if(starts_with(resp, "PIO:")) {
        unsigned int bitmap;
        if(sscanf(resp+4, "%x", &bitmap) != 1) return -1;
        for(int i=0; i<MAX_DIO_COUNT; ++i)
            values[i] = (bitmap >> i) & 1;
        *count = MAX_DIO_COUNT;
        return 0;
    }
    return -1;
}

int dio_write(const int *values, int count) {
    // Build bitmap
    unsigned int bitmap = 0;
    for(int i=0; i<count && i<MAX_DIO_COUNT; ++i)
        if(values[i]) bitmap |= (1<<i);
    char cmd[64], resp[64];
    snprintf(cmd, sizeof(cmd), "pio_write %X", bitmap);
    if(uart_cmd(cmd, resp, sizeof(resp)) < 0) return -1;
    // Expecting "OK"
    return starts_with(resp, "OK") ? 0 : -1;
}

// SERVO API

int servo_get(int *positions, int *count) {
    char resp[128];
    if(uart_cmd("ics_get_pos", resp, sizeof(resp)) < 0) return -1;
    // Example response: "SERVO:1200,1250,1230"
    if(starts_with(resp, "SERVO:")) {
        char *p = resp+6;
        int i = 0;
        while (i < MAX_SERVO_COUNT && p && *p) {
            positions[i++] = strtol(p, &p, 10);
            if(*p == ',') ++p;
        }
        *count = i;
        return 0;
    }
    return -1;
}

int servo_set(const int *positions, int count) {
    char cmd[128], resp[64];
    char *p = cmd;
    p += sprintf(p, "ics_set_pos ");
    for(int i=0; i<count && i<MAX_SERVO_COUNT; ++i)
        p += sprintf(p, "%d%c", positions[i], (i==count-1)?'\0':',');
    if(uart_cmd(cmd, resp, sizeof(resp)) < 0) return -1;
    return starts_with(resp, "OK") ? 0 : -1;
}

// ANALOG API

int analog_read(int *values, int *count) {
    char resp[128];
    if(uart_cmd("ad_read", resp, sizeof(resp)) < 0) return -1;
    // Example: "AD:1023,1000,900,850"
    if(starts_with(resp, "AD:")) {
        char *p = resp+3;
        int i = 0;
        while(i < MAX_AD_COUNT && p && *p) {
            values[i++] = strtol(p, &p, 10);
            if(*p == ',') ++p;
        }
        *count = i;
        return 0;
    }
    return -1;
}

// Parse JSON for /dio and /servo POST

int parse_json_int_array(const char *json, int *arr, int maxlen) {
    // Expects: {"values":[1,0,1,...]}
    const char *p = strstr(json, "\"values\"");
    if(!p) return -1;
    p = strchr(p, '[');
    if(!p) return -1;
    ++p;
    int n = 0;
    while(n<maxlen && *p && *p!=']') {
        arr[n++] = strtol(p, (char**)&p, 10);
        while(*p && *p!=',' && *p!=']') ++p;
        if(*p==',') ++p;
    }
    return n;
}

// HTTP Handlers

void handle_dio_get(int client) {
    int values[MAX_DIO_COUNT], count=0;
    if(dio_read(values, &count) < 0) {
        http_response(client, 500, "application/json", "{\"error\":\"dio_read failed\"}");
        return;
    }
    char body[MAX_JSON_SIZE], *p=body;
    p += sprintf(p, "{\"values\":[");
    for(int i=0; i<count; ++i)
        p += sprintf(p, "%d%s", values[i], (i==count-1)?"":",");
    p += sprintf(p, "]}");
    http_response(client, 200, "application/json", body);
}

void handle_dio_post(int client, const char *body) {
    int values[MAX_DIO_COUNT];
    int count = parse_json_int_array(body, values, MAX_DIO_COUNT);
    if(count <= 0) {
        http_response(client, 400, "application/json", "{\"error\":\"invalid JSON or missing 'values'\"}");
        return;
    }
    if(dio_write(values, count) < 0) {
        http_response(client, 500, "application/json", "{\"error\":\"dio_write failed\"}");
        return;
    }
    http_response(client, 200, "application/json", "{\"status\":\"ok\"}");
}

void handle_servo_get(int client) {
    int positions[MAX_SERVO_COUNT], count=0;
    if(servo_get(positions, &count) < 0) {
        http_response(client, 500, "application/json", "{\"error\":\"servo_get failed\"}");
        return;
    }
    char body[MAX_JSON_SIZE], *p=body;
    p += sprintf(p, "{\"positions\":[");
    for(int i=0; i<count; ++i)
        p += sprintf(p, "%d%s", positions[i], (i==count-1)?"":",");
    p += sprintf(p, "]}");
    http_response(client, 200, "application/json", body);
}

void handle_servo_post(int client, const char *body) {
    int positions[MAX_SERVO_COUNT];
    int count = parse_json_int_array(body, positions, MAX_SERVO_COUNT);
    if(count <= 0) {
        http_response(client, 400, "application/json", "{\"error\":\"invalid JSON or missing 'values'\"}");
        return;
    }
    if(servo_set(positions, count) < 0) {
        http_response(client, 500, "application/json", "{\"error\":\"servo_set failed\"}");
        return;
    }
    http_response(client, 200, "application/json", "{\"status\":\"ok\"}");
}

void handle_analog_get(int client) {
    int values[MAX_AD_COUNT], count=0;
    if(analog_read(values, &count) < 0) {
        http_response(client, 500, "application/json", "{\"error\":\"analog_read failed\"}");
        return;
    }
    char body[MAX_JSON_SIZE], *p=body;
    p += sprintf(p, "{\"values\":[");
    for(int i=0; i<count; ++i)
        p += sprintf(p, "%d%s", values[i], (i==count-1)?"":",");
    p += sprintf(p, "]}");
    http_response(client, 200, "application/json", body);
}

// Main HTTP Connection Handler

void handle_http(int client) {
    char req[MAX_REQ_SIZE] = {0};
    int r = read(client, req, sizeof(req)-1);
    if(r <= 0) { close(client); return; }
    req[r] = 0;

    // Parse method and path
    char method[8], path[64];
    sscanf(req, "%7s %63s", method, path);

    // Find body (for POST)
    char *body = strstr(req, "\r\n\r\n");
    if(body) body += 4; else body = "";

    // Routing
    if(strcmp(method, "GET")==0 && strcmp(path, "/dio")==0) {
        handle_dio_get(client);
    } else if(strcmp(method, "POST")==0 && strcmp(path, "/dio")==0) {
        handle_dio_post(client, body);
    } else if(strcmp(method, "GET")==0 && strcmp(path, "/servo")==0) {
        handle_servo_get(client);
    } else if(strcmp(method, "POST")==0 && strcmp(path, "/servo")==0) {
        handle_servo_post(client, body);
    } else if(strcmp(method, "GET")==0 && strcmp(path, "/analog")==0) {
        handle_analog_get(client);
    } else {
        http_notfound(client);
    }
    close(client);
}

// Server main
int main() {
    signal(SIGINT, int_handler);

    const char *uart_port = envd("KCB5_DEVICE_PORT", "/dev/ttyS1");
    int baudrate = atoi(envd("KCB5_UART_BAUDRATE", "115200"));
    const char *http_host = envd("HTTP_HOST", "0.0.0.0");
    int http_port = atoi(envd("HTTP_PORT", "8080"));

    // Open UART
    uart_fd = uart_open(uart_port, baudrate);
    if(uart_fd < 0) {
        fprintf(stderr, "Failed to open UART %s\n", uart_port);
        return 1;
    }

    // Open HTTP server socket
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if(server_fd < 0) { perror("socket"); return 1; }

    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(http_port);
    addr.sin_addr.s_addr = strcmp(http_host, "0.0.0.0") == 0 ? INADDR_ANY : inet_addr(http_host);

    if(bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(server_fd);
        return 1;
    }
    if(listen(server_fd, 8) < 0) { perror("listen"); close(server_fd); return 1; }

    fprintf(stderr, "KCB-5 HTTP Driver: Listening on %s:%d\n", http_host, http_port);

    while(keep_running) {
        struct sockaddr_in client_addr;
        socklen_t clen = sizeof(client_addr);
        int client = accept(server_fd, (struct sockaddr*)&client_addr, &clen);
        if(client < 0) {
            if(errno == EINTR) break;
            continue;
        }
        handle_http(client);
    }

    close(server_fd);
    close(uart_fd);
    fprintf(stderr, "KCB-5 HTTP Driver stopped.\n");
    return 0;
}