package product

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/cache"
)

type Product struct {
	ID    int64   `json:"id"`
	Name  string  `json:"name"`
	Price float64 `json:"price"`
}

type Service struct {
	db  *sql.DB
	rdb *cache.Client
	ttl time.Duration
}

func New(db *sql.DB, rdb *cache.Client, ttlSeconds int) *Service {
	return &Service{db: db, rdb: rdb, ttl: time.Duration(ttlSeconds) * time.Second}
}

func (s *Service) Register(r gin.IRouter) {
	r.GET("/products/:id", s.getByID)
	r.POST("/products", s.create)
	r.PUT("/products/:id", s.update)
}

func (s *Service) getByID(c *gin.Context) {
	id := c.Param("id")
	ctx := c.Request.Context()
	key := s.rdb.ProductKey(id)

	if cached, ok, err := s.rdb.Get(ctx, key); err == nil && ok {
		c.Data(http.StatusOK, "application/json; charset=utf-8", []byte(cached))
		return
	}

	var p Product
	err := s.db.QueryRowContext(ctx,
		`SELECT id, name, price FROM products WHERE id = $1`, id,
	).Scan(&p.ID, &p.Name, &p.Price)
	if errors.Is(err, sql.ErrNoRows) {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query failed"})
		return
	}

	if payload, err := json.Marshal(p); err == nil {
		_ = s.rdb.Set(ctx, key, string(payload), s.ttl)
	}

	c.JSON(http.StatusOK, p)
}

type upsertBody struct {
	Name  string  `json:"name"`
	Price float64 `json:"price"`
}

func (s *Service) create(c *gin.Context) {
	var body upsertBody
	if err := c.ShouldBindJSON(&body); err != nil || body.Name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "name and price are required"})
		return
	}

	var p Product
	err := s.db.QueryRowContext(c.Request.Context(),
		`INSERT INTO products (name, price) VALUES ($1, $2) RETURNING id, name, price`,
		body.Name, body.Price,
	).Scan(&p.ID, &p.Name, &p.Price)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert failed"})
		return
	}

	c.JSON(http.StatusCreated, p)
}

func (s *Service) update(c *gin.Context) {
	id := c.Param("id")
	var body upsertBody
	if err := c.ShouldBindJSON(&body); err != nil || body.Name == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "name and price are required"})
		return
	}

	ctx := c.Request.Context()
	var p Product
	err := s.db.QueryRowContext(ctx,
		`UPDATE products SET name = $1, price = $2 WHERE id = $3 RETURNING id, name, price`,
		body.Name, body.Price, id,
	).Scan(&p.ID, &p.Name, &p.Price)
	if errors.Is(err, sql.ErrNoRows) {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "update failed"})
		return
	}

	_ = s.rdb.Del(ctx, s.rdb.ProductKey(id))

	c.JSON(http.StatusOK, p)
}
