package hashpool

import (
	"context"
	"runtime"

	"golang.org/x/crypto/bcrypt"
)

type Pool struct {
	cost int
	sem  chan struct{}
}

func New(cost int) *Pool {
	limit := runtime.GOMAXPROCS(0)
	if limit < 1 {
		limit = 1
	}
	return &Pool{
		cost: cost,
		sem:  make(chan struct{}, limit),
	}
}

func (p *Pool) Hash(ctx context.Context, password string) (string, error) {
	if err := p.acquire(ctx); err != nil {
		return "", err
	}
	defer p.release()

	hash, err := bcrypt.GenerateFromPassword([]byte(password), p.cost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

func (p *Pool) Compare(ctx context.Context, hash, password string) error {
	if err := p.acquire(ctx); err != nil {
		return err
	}
	defer p.release()

	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
}

func (p *Pool) acquire(ctx context.Context) error {
	select {
	case p.sem <- struct{}{}:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (p *Pool) release() {
	<-p.sem
}
