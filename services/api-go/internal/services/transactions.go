package services

import (
	"context"

	"gorm.io/gorm"
)

// TransactionManager makes the application service the owner of one atomic write.
type TransactionManager struct {
	db *gorm.DB
}

func NewTransactionManager(db *gorm.DB) TransactionManager {
	return TransactionManager{db: db}
}

func (manager TransactionManager) WithinTransaction(ctx context.Context, work func(tx *gorm.DB) error) error {
	return manager.db.WithContext(ctx).Transaction(work)
}
