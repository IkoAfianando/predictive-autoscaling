package httpx

import (
	"strconv"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/metrics"
)

func Metrics(service, stack string) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		c.Next()

		route := c.FullPath()
		if route == "" {
			route = "unmatched"
		}

		metrics.RequestDuration.WithLabelValues(
			service,
			stack,
			c.Request.Method,
			route,
			strconv.Itoa(c.Writer.Status()),
		).Observe(time.Since(start).Seconds())
	}
}
