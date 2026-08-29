package config

import (
	"log"
	"os"
	"strconv"
)

type Config struct {
	ServiceName string // user | product | order
	StackName   string // go | rust | java | node
	Port        string // internal port, default 8080

	DatabaseURL string
	RedisURL    string

	BcryptCost      int
	DBPoolMax       int
	CacheTTLSeconds int

	UserServiceURL    string
	ProductServiceURL string
}

func Load() Config {
	c := Config{
		ServiceName:       getEnv("SERVICE_NAME", "user"),
		StackName:         getEnv("STACK_NAME", "go"),
		Port:              getEnv("PORT", "8080"),
		DatabaseURL:       getEnv("DATABASE_URL", "postgres://appuser:appsecret@localhost:5432/go_db"),
		RedisURL:          getEnv("REDIS_URL", "redis://localhost:6379"),
		BcryptCost:        getEnvInt("BCRYPT_COST", 10),
		DBPoolMax:         getEnvInt("DB_POOL_MAX", 20),
		CacheTTLSeconds:   getEnvInt("CACHE_TTL_SECONDS", 30),
		UserServiceURL:    getEnv("USER_SERVICE_URL", "http://go-user:8080"),
		ProductServiceURL: getEnv("PRODUCT_SERVICE_URL", "http://go-product:8080"),
	}
	return c
}

func getEnv(key, def string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return def
}

func getEnvInt(key string, def int) int {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			log.Printf("config: invalid int for %s=%q, using default %d", key, v, def)
			return def
		}
		return n
	}
	return def
}
