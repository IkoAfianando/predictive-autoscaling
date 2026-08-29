package user

import (
	"database/sql"
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"github.com/iko/predictive-autoscaling-thesis/services/go/internal/hashpool"
)

type Service struct {
	db     *sql.DB
	hasher *hashpool.Pool
}

func New(db *sql.DB, hasher *hashpool.Pool) *Service {
	return &Service{db: db, hasher: hasher}
}

func (s *Service) Register(r gin.IRouter) {
	r.POST("/users/register", s.register)
	r.POST("/users/login", s.login)
	r.GET("/users/:id", s.getByID)
}

type credentials struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

func (s *Service) register(c *gin.Context) {
	var body credentials
	if err := c.ShouldBindJSON(&body); err != nil || body.Username == "" || body.Password == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "username and password are required"})
		return
	}

	hash, err := s.hasher.Hash(c.Request.Context(), body.Password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "hash failed"})
		return
	}

	var id int64
	err = s.db.QueryRowContext(c.Request.Context(),
		`INSERT INTO users (username, password) VALUES ($1, $2) RETURNING id`,
		body.Username, hash,
	).Scan(&id)
	if err != nil {
		c.JSON(http.StatusConflict, gin.H{"error": "username already exists"})
		return
	}

	c.JSON(http.StatusCreated, gin.H{"id": id, "username": body.Username})
}

func (s *Service) login(c *gin.Context) {
	var body credentials
	if err := c.ShouldBindJSON(&body); err != nil || body.Username == "" || body.Password == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "username and password are required"})
		return
	}

	var (
		id   int64
		hash string
	)
	err := s.db.QueryRowContext(c.Request.Context(),
		`SELECT id, password FROM users WHERE username = $1`, body.Username,
	).Scan(&id, &hash)
	if errors.Is(err, sql.ErrNoRows) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid credentials"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query failed"})
		return
	}

	if err := s.hasher.Compare(c.Request.Context(), hash, body.Password); err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid credentials"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"token": uuid.NewString()})
}

func (s *Service) getByID(c *gin.Context) {
	id := c.Param("id")
	var (
		uid      int64
		username string
	)
	err := s.db.QueryRowContext(c.Request.Context(),
		`SELECT id, username FROM users WHERE id = $1`, id,
	).Scan(&uid, &username)
	if errors.Is(err, sql.ErrNoRows) {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query failed"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"id": uid, "username": username})
}
