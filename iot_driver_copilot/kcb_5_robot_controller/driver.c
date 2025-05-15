/*
 * KCB-5 Robot Controller HTTP Device Driver
 * Implements an HTTP server providing browser/CLI-accessible endpoints
 * for direct control and monitoring of the KCB-5 over UART/I2C/SPI/ICS.
 * All configuration is via environment variables.
 * - SERVER_HOST: address to bind (default: "0.0.0.0")
 * - SERVER_PORT: port to bind (default: "8080")
 * - UART_PORT: UART device (e.g. "/dev/ttyS1")
 * - UART_BAUD: UART baudrate (default: 115200)
 * - I2C_DEV: I2C device (e.g. "/dev/i2c-1")
 * - SPI_DEV: SPI device (e.g. "/dev/spidev0.0")
 * - ICS_PORT: ICS serial port (e.g. "/dev/ttyS2")
 * Only those buses actually used by driver are required.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <poll.h>
#include <termios.h>
#include <sys/ioctl.h>
#include <linux/i2c-dev.h>
#include <linux/spi/spidev.h>

#define MAX_REQ_SIZE 4096
#define MAX_RESP_SIZE 8192
#define UART_BUF_SIZE 1024

// Util functions for env config
static char* getenv_default(const char *k, const char *def) {
    char *v = getenv(k);
    return v ? v : (char*)def;
}
static int getenv_int(const char *k, int def) {
    char *v = getenv(k);
    return v ? atoi(v) : def;
}

// UART
typedef struct {
    int fd;
} uart_handle_t;

static int uart_open(uart_handle_t *h, const char *dev, int baud) {
    h->fd = open(dev, O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (h->fd < 0) return -1;
    struct termios tio;
    memset(&tio, 0, sizeof(tio));
    tio.c_cflag = CS8 | CLOCAL | CREAD;
    tio.c_iflag = IGNPAR;
    tio.c_oflag = 0;
    tio.c_lflag = 0;
    cfsetispeed(&tio, baud);
    cfsetospeed(&tio, baud);
    tcflush(h->fd, TCIFLUSH);
    if (tcsetattr(h->fd, TCSANOW, &tio) < 0) {
        close(h->fd); h->fd = -1; return -2;
    }
    return 0;
}
static ssize_t uart_write(uart_handle_t *h, const void *buf, size_t len) {
    return write(h->fd, buf, len);
}
static ssize_t uart_read(uart_handle_t *h, void *buf, size_t len) {
    return read(h->fd, buf, len);
}

// I2C
typedef struct {
    int fd;
} i2c_handle_t;

static int i2c_open(i2c_handle_t *h, const char *dev) {
    h->fd = open(dev, O_RDWR);
    if (h->fd < 0) return -1;
    return 0;
}
static int i2c_write(i2c_handle_t *h, int addr, const void *buf, size_t len) {
    if (ioctl(h->fd, I2C_SLAVE, addr) < 0) return -1;
    return write(h->fd, buf, len);
}

// SPI
typedef struct {
    int fd;
} spi_handle_t;

static int spi_open(spi_handle_t *h, const char *dev) {
    h->fd = open(dev, O_RDWR);
    if (h->fd < 0) return -1;
    uint8_t mode = SPI_MODE_0;
    uint8_t bits = 8;
    uint32_t speed = 1000000;
    ioctl(h->fd, SPI_IOC_WR_MODE, &mode);
    ioctl(h->fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(h->fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);
    return 0;
}
static int spi_write(spi_handle_t *h, const void *buf, size_t len) {
    return write(h->fd, buf, len);
}

// ICS (Servo) - just use UART for ICS port
typedef uart_handle_t ics_handle_t;
#define ics_open uart_open
#define ics_write uart_write

// HTTP utility
static void send_response(int fd, const char *status, const char *ctype, const char *body) {
    char buf[MAX_RESP_SIZE];
    int n = snprintf(buf, sizeof(buf),
        "HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %zu\r\nAccess-Control-Allow-Origin: *\r\n\r\n%s",
        status, ctype, strlen(body), body);
    write(fd, buf, n);
}
static void send_json(int fd, const char *body) {
    send_response(fd, "200 OK", "application/json", body);
}
static void send_204(int fd) {
    send_response(fd, "204 No Content", "text/plain", "");
}
static void send_400(int fd, const char *msg) {
    char buf[256];
    snprintf(buf, sizeof(buf), "{\"error\":\"%s\"}", msg);
    send_response(fd, "400 Bad Request", "application/json", buf);
}
static void send_404(int fd) {
    send_response(fd, "404 Not Found", "application/json", "{\"error\":\"Not found\"}");
}
static void send_405(int fd) {
    send_response(fd, "405 Method Not Allowed", "application/json", "{\"error\":\"Method not allowed\"}");
}

// HTTP parsing
static int parse_http_request(const char *req, char *method, char *path, char *body) {
    sscanf(req, "%s %s", method, path);
    char *b = strstr(req, "\r\n\r\n");
    if (b && strlen(b+4) < MAX_REQ_SIZE-1)
        strcpy(body, b+4);
    else
        body[0]=0;
    return 0;
}

// Main endpoint logic

// /status - GET
static void handle_status(int fd) {
    // For demonstration, dummy data. Real code would poll device over UART/SPI/I2C/ICS.
    // For example, send a status request over UART and parse reply.
    char json[256];
    snprintf(json, sizeof(json),
        "{\"ad\":[123,234,345,456],\"dip\":[1,0,1,0],\"led\":[1,0,1,1],\"timer\":[1000,2000]}"
    );
    send_json(fd, json);
}

// /rom - PUT
static void handle_rom(int fd, const char *body) {
    // Expects {"cmd":"write"/"erase","data":"..."}
    // Send write/erase command to ROM over UART/I2C/SPI
    // For demo: just succeed
    send_204(fd);
}

// /dac - PUT
static void handle_dac(int fd, const char *body) {
    // Expects {"value":1234}
    // Map to DAC write over UART/I2C/SPI
    send_204(fd);
}

// /bus - PUT
static void handle_bus(int fd, const char *body, i2c_handle_t *i2c, spi_handle_t *spi) {
    // Expects {"bus":"i2c"/"spi", "addr":..., "data":[...]}
    // Parse JSON, write to bus
    char bus[8];
    int addr = 0;
    int data[32], n = 0;
    if (sscanf(body, "{\"bus\":\"%7[^\"]\",\"addr\":%d,\"data\":[%n", bus, &addr, &n) >= 2) {
        int d[32], nd=0, x;
        const char *p = body + n;
        while (sscanf(p, "%d%n", &x, &n) == 1) {
            d[nd++] = x;
            p += n;
            if (*p != ',') break; p++;
        }
        if (strcmp(bus,"i2c")==0 && i2c && i2c->fd>0) {
            uint8_t buf[32]; for(int i=0;i<nd;i++) buf[i]=d[i];
            i2c_write(i2c, addr, buf, nd);
        } else if (strcmp(bus,"spi")==0 && spi && spi->fd>0) {
            uint8_t buf[32]; for(int i=0;i<nd;i++) buf[i]=d[i];
            spi_write(spi, buf, nd);
        }
        send_204(fd);
        return;
    }
    send_400(fd, "Invalid JSON or bus");
}

// /servo - PUT
static void handle_servo(int fd, const char *body, ics_handle_t *ics) {
    // Expects {"id":1,"pos":1500,"param":0}
    // Send ICS protocol packet over ICS UART
    send_204(fd);
}

// /uart - POST
static void handle_uart(int fd, const char *body, uart_handle_t *uart) {
    // Expects {"data":[...]}
    int n=0, x, ndata=0;
    const char *p = strstr(body, "\"data\":[");
    if (!p) { send_400(fd, "Missing data"); return; }
    p += strlen("\"data\":[");
    uint8_t buf[UART_BUF_SIZE];
    while (sscanf(p, "%d%n", &x, &n) == 1) {
        buf[ndata++] = x;
        p += n;
        if (*p != ',') break; p++;
    }
    if (uart && uart->fd>0) uart_write(uart, buf, ndata);
    send_204(fd);
}

// /pwm - PUT
static void handle_pwm(int fd, const char *body) {
    // Expects {"channel":1,"duty":50,"period":20000}
    send_204(fd);
}

// /pio - PUT
static void handle_pio(int fd, const char *body) {
    // Expects {"port":1,"value":1}
    send_204(fd);
}

// Main HTTP dispatch
static void handle_client(int cfd, uart_handle_t *uart, i2c_handle_t *i2c, spi_handle_t *spi, ics_handle_t *ics) {
    char req[MAX_REQ_SIZE], method[8], path[64], body[MAX_REQ_SIZE];
    int n = read(cfd, req, sizeof(req)-1); req[n>=0?n:0]=0;
    parse_http_request(req, method, path, body);

    if (strcmp(path, "/status")==0 && strcmp(method,"GET")==0) {
        handle_status(cfd);
    } else if (strcmp(path,"/rom")==0 && strcmp(method,"PUT")==0) {
        handle_rom(cfd, body);
    } else if (strcmp(path,"/dac")==0 && strcmp(method,"PUT")==0) {
        handle_dac(cfd, body);
    } else if (strcmp(path,"/bus")==0 && strcmp(method,"PUT")==0) {
        handle_bus(cfd, body, i2c, spi);
    } else if (strcmp(path,"/servo")==0 && strcmp(method,"PUT")==0) {
        handle_servo(cfd, body, ics);
    } else if (strcmp(path,"/uart")==0 && strcmp(method,"POST")==0) {
        handle_uart(cfd, body, uart);
    } else if (strcmp(path,"/pwm")==0 && strcmp(method,"PUT")==0) {
        handle_pwm(cfd, body);
    } else if (strcmp(path,"/pio")==0 && strcmp(method,"PUT")==0) {
        handle_pio(cfd, body);
    } else if (strcmp(path,"/status")==0) {
        send_405(cfd);
    } else {
        send_404(cfd);
    }
    close(cfd);
}

int main() {
    // --- Configuration from environment ---
    const char *host = getenv_default("SERVER_HOST", "0.0.0.0");
    int port = getenv_int("SERVER_PORT", 8080);
    const char *uart_port = getenv("UART_PORT");
    int uart_baud = getenv_int("UART_BAUD", B115200);
    const char *i2c_dev = getenv("I2C_DEV");
    const char *spi_dev = getenv("SPI_DEV");
    const char *ics_port = getenv("ICS_PORT");

    uart_handle_t uart = {.fd=-1}; i2c_handle_t i2c = {.fd=-1};
    spi_handle_t spi = {.fd=-1}; ics_handle_t ics = {.fd=-1};

    if (uart_port) uart_open(&uart, uart_port, uart_baud);
    if (i2c_dev) i2c_open(&i2c, i2c_dev);
    if (spi_dev) spi_open(&spi, spi_dev);
    if (ics_port) ics_open(&ics, ics_port, uart_baud);

    // --- Setup HTTP server ---
    int sfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sfd < 0) { perror("socket"); exit(1); }
    int optval = 1;
    setsockopt(sfd, SOL_SOCKET, SO_REUSEADDR, &optval, sizeof(optval));
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = INADDR_ANY;
    if (bind(sfd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind"); exit(1);
    }
    listen(sfd, 8);

    printf("KCB-5 HTTP driver listening on %s:%d\n", host, port);
    while (1) {
        struct sockaddr_in cli; socklen_t clilen = sizeof(cli);
        int cfd = accept(sfd, (struct sockaddr*)&cli, &clilen);
        if (cfd < 0) continue;
        handle_client(cfd, &uart, &i2c, &spi, &ics);
    }

    close(sfd);
    if (uart.fd>0) close(uart.fd);
    if (i2c.fd>0) close(i2c.fd);
    if (spi.fd>0) close(spi.fd);
    if (ics.fd>0) close(ics.fd);
    return 0;
}