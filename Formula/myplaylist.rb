class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/54/7a/138ad05d9d2d1c650d7faf24fb816a109f28db319c6b2dbe2f113ac66ffc/myplaylist-0.4.3-py3-none-any.whl",,,,,,,,,,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "af17c8662d443b952b0fdd3efe85e5f7cb25ea6406a43f4e09aeec572063b8bf"
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
