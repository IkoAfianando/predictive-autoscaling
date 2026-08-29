package order

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

type Service struct {
	db                *sql.DB
	client            *http.Client
	userServiceURL    string
	productServiceURL string
}

func New(db *sql.DB, userServiceURL, productServiceURL string) *Service {
	return &Service{
		db:                db,
		client:            &http.Client{Timeout: 5 * time.Second},
		userServiceURL:    userServiceURL,
		productServiceURL: productServiceURL,
	}
}

func (s *Service) Register(r gin.IRouter) {
	r.POST("/orders", s.create)
	r.GET("/orders/:id", s.getByID)
}

type createBody struct {
	UserID    int64 `json:"user_id"`
	ProductID int64 `json:"product_id"`
	Qty       int   `json:"qty"`
}

func (s *Service) create(c *gin.Context) {
	var body createBody
	if err := c.ShouldBindJSON(&body); err != nil || body.UserID == 0 || body.ProductID == 0 || body.Qty <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "user_id, product_id and positive qty are required"})
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()

	userURL := fmt.Sprintf("%s/users/%d", s.userServiceURL, body.UserID)
	productURL := fmt.Sprintf("%s/products/%d", s.productServiceURL, body.ProductID)

	errCh := make(chan error, 2)
	go func() { errCh <- s.checkExists(ctx, userURL, "user") }()
	go func() { errCh <- s.checkExists(ctx, productURL, "product") }()

	var fanoutErr error
	for i := 0; i < 2; i++ {
		if err := <-errCh; err != nil && fanoutErr == nil {
			fanoutErr = err
		}
	}
	if fanoutErr != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": fanoutErr.Error()})
		return
	}

	var id int64
	err := s.db.QueryRowContext(c.Request.Context(),
		`INSERT INTO orders (user_id, product_id, qty) VALUES ($1, $2, $3) RETURNING id`,
		body.UserID, body.ProductID, body.Qty,
	).Scan(&id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "insert failed"})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"id":         id,
		"user_id":    body.UserID,
		"product_id": body.ProductID,
		"qty":        body.Qty,
	})
}

func (s *Service) checkExists(ctx context.Context, url, kind string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return fmt.Errorf("%s lookup failed", kind)
	}
	resp, err := s.client.Do(req)
	if err != nil {
		return fmt.Errorf("%s service unreachable", kind)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return nil
	}
	return fmt.Errorf("%s not found", kind)
}

func (s *Service) getByID(c *gin.Context) {
	id := c.Param("id")
	var (
		oid       int64
		userID    int64
		productID int64
		qty       int
	)
	err := s.db.QueryRowContext(c.Request.Context(),
		`SELECT id, user_id, product_id, qty FROM orders WHERE id = $1`, id,
	).Scan(&oid, &userID, &productID, &qty)
	if errors.Is(err, sql.ErrNoRows) {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query failed"})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"id":         oid,
		"user_id":    userID,
		"product_id": productID,
		"qty":        qty,
	})
}
