class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/fe/fe/e4a4fe8d4c41402313973746733198ce91bc0921961d6046c89925e95b58/myplaylist-0.3.14-py3-none-any.whl",,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "156ea3a49b774a4474e84e30a4403c9364f8bde3f8315b641ae800d7862b4245"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3.11", "-m", "venv", venv
    system venv/"bin/pip", "install", "myplaylist==#{version}"
    bin.install_symlink venv/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
