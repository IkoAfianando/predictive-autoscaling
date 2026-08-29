package main

import (
	"context"
	"database/sql"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/cache"
	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/config"
	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/db"
	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/hashpool"
	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/httpx"
	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/order"
	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/product"
	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/user"
)

type registrar interface {
	Register(r gin.IRouter)
}

func main() {
	cfg := config.Load()
	log.Printf("starting service=%s stack=%s port=%s", cfg.ServiceName, cfg.StackName, cfg.Port)

	startupCtx, cancelStartup := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancelStartup()

	database, err := db.Connect(startupCtx, cfg.DatabaseURL, cfg.DBPoolMax)
	if err != nil {
		log.Fatalf("fatal: %v", err)
	}
	defer database.Close()

	if err := db.Migrate(startupCtx, database); err != nil {
		log.Fatalf("fatal: %v", err)
	}

	redisClient, err := cache.Connect(startupCtx, cfg.RedisURL, cfg.StackName)
	if err != nil {
		log.Fatalf("fatal: %v", err)
	}
	defer redisClient.Close()

	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(httpx.Metrics(cfg.ServiceName, cfg.StackName))

	router.GET("/health", healthHandler(database, redisClient))
	router.GET("/metrics", gin.WrapH(promhttp.Handler()))

	var svc registrar
	switch cfg.ServiceName {
	case "user":
		svc = user.New(database, hashpool.New(cfg.BcryptCost))
	case "product":
		svc = product.New(database, redisClient, cfg.CacheTTLSeconds)
	case "order":
		svc = order.New(database, cfg.UserServiceURL, cfg.ProductServiceURL)
	default:
		log.Fatalf("fatal: unknown SERVICE_NAME %q (want user|product|order)", cfg.ServiceName)
	}
	svc.Register(router)

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           router,
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("fatal: server: %v", err)
		}
	}()
	log.Printf("listening on :%s", cfg.Port)

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("shutdown: %v", err)
	}
}

func healthHandler(database *sql.DB, redisClient *cache.Client) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
		defer cancel()

		if err := database.PingContext(ctx); err != nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{"status": "degraded", "db": err.Error()})
			return
		}
		if err := redisClient.Ping(ctx); err != nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{"status": "degraded", "redis": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}
