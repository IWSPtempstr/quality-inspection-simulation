package conf

import "testing"

func TestLoadUsesDevelopmentDefaults(t *testing.T) {
	config, err := Load(func(string) (string, bool) { return "", false })
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if config.Environment != "development" || config.HTTPAddress != ":8080" {
		t.Fatalf("config = %#v, want development defaults", config)
	}
}

func TestLoadRejectsBlankConfiguredAddress(t *testing.T) {
	_, err := Load(func(key string) (string, bool) {
		if key == "HTTP_ADDR" {
			return " ", true
		}
		return "", false
	})
	if err == nil {
		t.Fatal("Load() error = nil, want validation error")
	}
}
