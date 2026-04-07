class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/2f/6b/12096d25c3828c96322bd2292ad17e0600e6472e23eb4760ff3320cd38b2/myplaylist-0.3.20-py3-none-any.whl",,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "5358e438ea0fa13667056ab299082585635bd5a4bc43bcb6e70343d6d6108e55"
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
